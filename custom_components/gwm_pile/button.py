"""Explicit Home Assistant actions for starting and stopping charging."""

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError

from .api import PileError
from .entity import PileEntity


async def async_setup_entry(_hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities([ChargingButton(c, True), ChargingButton(c, False)])


class ChargingButton(PileEntity, ButtonEntity):
    def __init__(self, coordinator, enable):
        key, name = ("start_charging", "启动充电") if enable else ("stop_charging", "停止充电")
        super().__init__(coordinator, key, name)
        self._enable = enable
        self._attr_icon = "mdi:ev-station" if enable else "mdi:stop-circle-outline"

    async def async_press(self):
        try:
            await self.coordinator.async_set_charging(self._enable)
        except PileError as error:
            raise HomeAssistantError(str(error)) from error
