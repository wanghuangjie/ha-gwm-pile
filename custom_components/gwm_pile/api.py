"""Authenticated calls to the GWM home charging service."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime
import json
import time

from aiohttp import ClientError, ClientSession, ClientTimeout

from .vendor.china_client import ChinaAuthState, ChinaClient, ChinaClientConfig, ChinaCredentials
from .vendor.china_crypto import DEFAULT_NOTE_ID, default_sign
from .vendor.errors import GwmAuthenticationError, GwmClientError

BASE_URL = "https://energy-api.gwm.com.cn/api-pile/v1/app/pile-control"
STOPPED = 2
CHARGING = 3
CONNECTED = 1


class PileError(Exception):
    """A safe error that contains neither account data nor tokens."""


class PileAuthenticationError(PileError):
    """The charger gateway rejected the account session."""


def encode_state(state: ChinaAuthState) -> dict:
    payload = asdict(state)
    if state.verification_requested_at is not None:
        payload["verification_requested_at"] = state.verification_requested_at.isoformat()
    return payload


def decode_state(payload: dict) -> ChinaAuthState:
    data = dict(payload)
    if data.get("verification_requested_at"):
        data["verification_requested_at"] = datetime.fromisoformat(data["verification_requested_at"])
    return ChinaAuthState(**data)


def number(value):
    """Read a nullable number as emitted by the charger API."""
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


class PileClient:
    """Read state and send explicit user-requested charging actions."""

    def __init__(
        self,
        session: ClientSession,
        pile_code: str | None,
        phone: str,
        state: ChinaAuthState,
        persist: Callable[[ChinaAuthState], Awaitable[None]],
    ) -> None:
        self.session = session
        self.pile_code = pile_code
        self.credentials = ChinaCredentials(phone, state.device_id)
        if not state.matches(self.credentials):
            raise PileAuthenticationError("Session belongs to another account")
        self.state = state
        self.persist = persist
        self.lock = asyncio.Lock()

    async def _save_state(self, state: ChinaAuthState) -> None:
        await self.persist(state)
        self.state = state

    async def _refresh(self) -> None:
        try:
            async with ChinaClient(ChinaClientConfig()) as client:
                result = await client.refresh_session(
                    self.credentials, self.state, on_state=self._save_state
                )
                await self._save_state(result.state)
        except GwmAuthenticationError as error:
            raise PileAuthenticationError("长城账号需要重新登录") from error
        except GwmClientError as error:
            raise PileError("暂时无法续期长城账号会话") from error

    async def _request(self, route: str, payload: dict):
        state = self.state
        url = f"{BASE_URL}/{route}"
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "SourceApp": "GWM",
            "SourceType": "ANDROID",
            "SourceAppVer": "2.2.3",
            "SourceAppCode": "2230",
            "AppId": "GWM-APP-ANDROID-1100018",
            "NoteId": DEFAULT_NOTE_ID,
            "cVer": "2.2.3",
            "vehicleVersion": "13",
            "User-Agent": "okhttp/4.2.2",
            "Authorization": state.bean_tech_access_token or "",
            "accessToken": state.bean_tech_access_token or "",
            "G-TOKEN": state.g_token or "",
            "ssoId": state.user_id or "",
            "beanId": state.bean_id or "",
            "Timestamp": str(time.time_ns() // 1_000_000),
            "DeviceId": state.device_id,
            "tokenId": state.auto_ai_token_id or "",
            "ampToken": state.pt_token or "",
        }
        headers["Sign"] = default_sign("POST", url, body, headers)
        headers["TimeStamp"] = headers.pop("Timestamp")

        try:
            async with self.session.post(
                url, data=body.encode(), headers=headers,
                timeout=ClientTimeout(total=12), allow_redirects=False,
            ) as response:
                if response.status in (401, 403):
                    raise PileAuthenticationError("家充桩服务拒绝账号会话")
                if response.status != 200:
                    raise PileError(f"家充桩服务返回 HTTP {response.status}")
                data = await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError) as error:
            raise PileError("无法读取长城家充桩服务响应") from error

        if not isinstance(data, dict):
            raise PileError("家充桩服务返回了未知格式")
        code = str(data.get("code", ""))
        if code in {"401", "1281012", "550004"}:
            raise PileAuthenticationError("家充桩服务拒绝账号会话")
        if data.get("successful") is not True:
            safe_code = code if code.isascii() and code.isdecimal() else "unknown"
            raise PileError(f"家充桩操作失败（{safe_code}）")
        return data.get("data")

    async def _read(self, route: str, payload: dict):
        if not self.state.complete:
            await self._refresh()
        try:
            return await self._request(route, payload)
        except PileAuthenticationError:
            await self._refresh()
            return await self._request(route, payload)

    async def _status(self) -> dict:
        if not self.pile_code:
            raise PileError("尚未选择家充桩")
        status = await self._read("query-pile-status", {"pileCode": self.pile_code})
        if not isinstance(status, dict) or status.get("pileCode") != self.pile_code:
            raise PileError("响应与当前家充桩不匹配")
        return status

    async def status(self) -> dict:
        async with self.lock:
            return await self._status()

    async def _recent_history(self) -> dict:
        history = await self._read(
            "all-charge-history", {"pageSize": 10, "pageIndex": 1, "viewType": 1}
        )
        if not isinstance(history, dict) or not isinstance(history.get("chargeHistoryDetails"), list):
            raise PileError("家充桩服务返回了未知的充电记录格式")
        return history

    async def recent_pile_codes(self) -> tuple[str, ...]:
        """Return candidates from recent records, which can omit bound chargers."""
        async with self.lock:
            history = await self._recent_history()
        return tuple(dict.fromkeys(
            row["pileCode"]
            for row in history["chargeHistoryDetails"]
            if isinstance(row, dict) and isinstance(row.get("pileCode"), str) and row["pileCode"]
        ))

    async def history(self) -> dict:
        async with self.lock:
            history = await self._recent_history()
        # A shared account can contain records from multiple chargers.
        records = [row for row in history["chargeHistoryDetails"]
                   if isinstance(row, dict) and row.get("pileCode") == self.pile_code]
        return {"account_record_count": number(history.get("totalCount")), "recent_records": records}

    async def set_charging(self, enable: bool) -> dict:
        """Send at most one write and confirm its result via status polling."""
        before, target = (STOPPED, CHARGING) if enable else (CHARGING, STOPPED)
        route = "start-charge" if enable else "stop-charge"
        async with self.lock:
            status = await self._status()
            if number(status.get("gunStatus")) == target:
                return status
            if number(status.get("gunStatus")) != before or (
                enable and number(status.get("gunConnectStatus")) != CONNECTED
            ):
                raise PileError("当前桩状态不允许执行此操作")
            await self._request(route, {"pileCode": self.pile_code})
            for _ in range(8):
                await asyncio.sleep(2)
                status = await self._status()
                if number(status.get("gunStatus")) == target:
                    return status
            raise PileError("长城云已接收指令，尚未确认充电状态变化")
