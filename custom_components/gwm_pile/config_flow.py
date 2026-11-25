"""SMS onboarding and one-time import of an existing verified session."""

from __future__ import annotations

import hashlib
import re
from uuid import uuid4

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectOptionDict, SelectSelector, SelectSelectorConfig
from homeassistant.helpers.storage import Store

from .api import PileClient, PileError, decode_state, encode_state
from .const import BOOTSTRAP_KEY, DOMAIN
from .vendor.china_client import (
    ChinaAuthenticated,
    ChinaClient,
    ChinaClientConfig,
    ChinaCredentials,
    ChinaVerificationRequired,
)
from .vendor.errors import GwmClientError

_PILE_CODE = re.compile(r"[A-Z0-9_-]{6,64}")
_MANUAL = "__manual__"


def session_store(hass, pile_code):
    key = hashlib.sha256(pile_code.encode()).hexdigest()[:24]
    return Store(hass, 1, f"{DOMAIN}.session.{key}", private=True)


class GwmPileConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a charger with a mainland China GWM account."""

    VERSION = 1

    async def async_step_import(self, _import_data):
        seed = await Store(self.hass, 1, BOOTSTRAP_KEY, private=True).async_load()
        if not seed:
            return self.async_abort(reason="no_bootstrap")
        pile_code = seed["pile_code"]
        await self.async_set_unique_id(pile_code)
        self._abort_if_unique_id_configured()
        state = decode_state(seed["state"])
        credentials = ChinaCredentials(seed["phone"], state.device_id)
        if not state.complete or not state.matches(credentials):
            return self.async_abort(reason="invalid_session")
        await session_store(self.hass, pile_code).async_save(
            {"phone": seed["phone"], "state": encode_state(state)}
        )
        return self.async_create_entry(title="长城家充桩", data={"pile_code": pile_code})

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            phone = user_input["phone"].strip()
            if not re.fullmatch(r"1[3-9][0-9]{9}", phone):
                errors["phone"] = "invalid_phone"
            if not errors:
                self._credentials = ChinaCredentials(phone, uuid4().hex)
                return await self._request_sms()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("phone"): str}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data):
        self._reauth_entry = self._get_reauth_entry()
        self._pile_code = entry_data["pile_code"]
        stored = await session_store(self.hass, self._pile_code).async_load()
        if not stored:
            return await self.async_step_reauth_phone()
        state = decode_state(stored["state"])
        self._credentials = ChinaCredentials(stored["phone"], state.device_id)
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({}))

    async def async_step_reauth_phone(self, user_input=None):
        errors = {}
        if user_input is not None:
            phone = user_input["phone"].strip()
            if re.fullmatch(r"1[3-9][0-9]{9}", phone):
                self._credentials = ChinaCredentials(phone, uuid4().hex)
                self._verify_reauth_pile = True
                return await self._request_sms()
            errors["phone"] = "invalid_phone"
        return self.async_show_form(
            step_id="reauth_phone",
            data_schema=vol.Schema({vol.Required("phone"): str}),
            errors=errors,
        )

    async def async_step_reauth_confirm(self, _user_input=None):
        return await self._request_sms()

    async def _request_sms(self):
        try:
            async with ChinaClient(ChinaClientConfig()) as client:
                result = await client.authenticate(self._credentials)
        except GwmClientError:
            return self.async_abort(reason="cannot_connect")
        if not isinstance(result, ChinaVerificationRequired) or not result.code_requested:
            return self.async_abort(reason="verification_unavailable")
        self._verification_state = result.state
        return await self.async_step_sms()

    async def async_step_sms(self, user_input=None):
        errors = {}
        if user_input is not None:
            code = user_input["code"].strip()
            if not re.fullmatch(r"[0-9]{4,8}", code):
                errors["code"] = "invalid_code"
            else:
                try:
                    async with ChinaClient(ChinaClientConfig()) as client:
                        result = await client.authenticate(
                            self._credentials, state=self._verification_state, verification_code=code,
                        )
                except GwmClientError:
                    errors["base"] = "cannot_connect"
                else:
                    if isinstance(result, ChinaAuthenticated):
                        self._auth_state = result.state
                        if hasattr(self, "_reauth_entry"):
                            if getattr(self, "_verify_reauth_pile", False):
                                try:
                                    await self._client(self._pile_code).status()
                                except PileError:
                                    return self.async_abort(reason="pile_unavailable")
                            await self._save_session(self._pile_code)
                            return self.async_update_reload_and_abort(self._reauth_entry)
                        return await self._discover_piles()
                    errors["code"] = "invalid_code"
        return self.async_show_form(
            step_id="sms", data_schema=vol.Schema({vol.Required("code"): str}), errors=errors,
        )

    async def _remember_session(self, state):
        self._auth_state = state

    def _client(self, pile_code):
        return PileClient(
            async_get_clientsession(self.hass), pile_code, self._credentials.phone,
            self._auth_state, self._remember_session,
        )

    async def _save_session(self, pile_code):
        await session_store(self.hass, pile_code).async_save(
            {"phone": self._credentials.phone, "state": encode_state(self._auth_state)}
        )

    async def _create_pile_entry(self, pile_code):
        await self.async_set_unique_id(pile_code)
        self._abort_if_unique_id_configured()
        await self._save_session(pile_code)
        return self.async_create_entry(title="长城家充桩", data={"pile_code": pile_code})

    async def _discover_piles(self):
        try:
            codes = await self._client(None).recent_pile_codes()
        except PileError:
            return await self.async_step_manual_pile(errors={"base": "history_unavailable"})
        self._suggested_piles = tuple(code for code in codes if _PILE_CODE.fullmatch(code))
        if self._suggested_piles:
            return await self.async_step_select_pile()
        return await self.async_step_manual_pile()

    async def async_step_select_pile(self, user_input=None):
        if user_input is not None:
            pile_code = user_input["pile_code"]
            if pile_code == _MANUAL:
                return await self.async_step_manual_pile()
            if pile_code in self._suggested_piles:
                return await self.async_step_manual_pile({"pile_code": pile_code})

        options = [
            SelectOptionDict(value=code, label=code) for code in self._suggested_piles
        ]
        options.append(SelectOptionDict(value=_MANUAL, label="手动输入编号"))
        choice = (
            vol.Required("pile_code", default=self._suggested_piles[0])
            if len(self._suggested_piles) == 1 else vol.Required("pile_code")
        )
        return self.async_show_form(
            step_id="select_pile",
            data_schema=vol.Schema({choice: SelectSelector(SelectSelectorConfig(options=options))}),
        )

    async def async_step_manual_pile(self, user_input=None, *, errors=None):
        errors = errors or {}
        if user_input is not None:
            pile_code = user_input["pile_code"].strip().upper()
            if not _PILE_CODE.fullmatch(pile_code):
                errors["pile_code"] = "invalid_pile"
            else:
                try:
                    await self._client(pile_code).status()
                except PileError:
                    errors["pile_code"] = "pile_unavailable"
                else:
                    return await self._create_pile_entry(pile_code)
        return self.async_show_form(
            step_id="manual_pile",
            data_schema=vol.Schema({vol.Required("pile_code"): str}),
            errors=errors,
        )
