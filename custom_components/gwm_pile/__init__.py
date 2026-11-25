"""Home Assistant integration for GWM cloud-connected home chargers."""

from datetime import timedelta
import logging
from time import monotonic

from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PileAuthenticationError, PileClient, PileError, decode_state, encode_state
from .config_flow import session_store
from .const import DOMAIN

LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]
CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


async def async_setup(hass, config):
    """Schedule the one-time import when requested in configuration.yaml."""
    if DOMAIN in config and not hass.config_entries.async_entries(DOMAIN):
        hass.async_create_task(hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_IMPORT}))
    return True


async def async_setup_entry(hass, entry):
    """Restore a private account session and set up charger entities."""
    pile_code = entry.data["pile_code"]
    store = session_store(hass, pile_code)
    stored = await store.async_load()
    if not stored:
        raise ConfigEntryAuthFailed("找不到长城家充桩账号会话，请重新登录")

    async def persist(state):
        await store.async_save({"phone": stored["phone"], "state": encode_state(state)})

    client = PileClient(
        async_get_clientsession(hass), pile_code, stored["phone"],
        decode_state(stored["state"]), persist,
    )
    coordinator = PileCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass, entry):
    await session_store(hass, entry.data["pile_code"]).async_remove()


class PileCoordinator(DataUpdateCoordinator):
    """Poll live status and refresh account history less frequently."""

    def __init__(self, hass, entry, client):
        super().__init__(
            hass, LOGGER, name=DOMAIN, config_entry=entry,
            update_interval=timedelta(seconds=30), always_update=False,
        )
        self.client = client
        self._history_due = 0
        self._history = {}

    async def _async_update_data(self):
        try:
            status = await self.client.status()
            if monotonic() >= self._history_due:
                self._history = await self.client.history()
                self._history_due = monotonic() + 300
        except PileAuthenticationError as error:
            raise ConfigEntryAuthFailed(str(error)) from error
        except PileError as error:
            raise UpdateFailed(str(error)) from error
        return {"status": status, **self._history}

    async def async_set_charging(self, enable):
        status = await self.client.set_charging(enable)
        self._history_due = 0
        self.async_set_updated_data({"status": status, **self._history})
