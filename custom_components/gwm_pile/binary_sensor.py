"""Charger connection and charging state."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .api import CHARGING, CONNECTED, STOPPED, number
from .entity import PileEntity


async def async_setup_entry(_hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities([
        PileBinarySensor(c, "plugged_in", "已插枪", BinarySensorDeviceClass.PLUG),
        PileBinarySensor(c, "charging", "正在充电", BinarySensorDeviceClass.BATTERY_CHARGING),
    ])


class PileBinarySensor(PileEntity, BinarySensorEntity):
    def __init__(self, coordinator, key, name, device_class):
        super().__init__(coordinator, key, name)
        self._attr_device_class = device_class
        self._key = key

    @property
    def is_on(self):
        if self._key == "plugged_in":
            connected = number(self.status.get("gunConnectStatus"))
            return connected == CONNECTED if connected in (0, CONNECTED) else None
        active = number(self.status.get("gunStatus"))
        if active in (STOPPED, CHARGING):
            return active == CHARGING
        return False if number(self.status.get("gunConnectStatus")) == 0 else None

    @property
    def extra_state_attributes(self):
        return {"gun_status": self.status.get("gunStatus"), "gun_connect_status": self.status.get("gunConnectStatus")}
