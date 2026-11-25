"""Charging session and history sensors."""

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import UnitOfElectricCurrent, UnitOfElectricPotential, UnitOfEnergy, UnitOfTime

from .api import number
from .entity import PileEntity

MEASUREMENTS = (
    ("current", "充电电流", "chargedCurrentOri", SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE),
    ("voltage", "充电电压", "chargedVoltageOri", SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT),
    ("energy", "本次充电量", "chargedPowerOri", SensorDeviceClass.ENERGY, UnitOfEnergy.KILO_WATT_HOUR),
    ("duration", "本次充电时长", "chargedTimeOri", SensorDeviceClass.DURATION, UnitOfTime.MINUTES),
)


async def async_setup_entry(_hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities([
        *(Measurement(coordinator, *m) for m in MEASUREMENTS),
        HistoryCount(coordinator),
        FaultCode(coordinator),
    ])


class Measurement(PileEntity, SensorEntity):
    def __init__(self, coordinator, key, name, field, device_class, unit):
        super().__init__(coordinator, key, name)
        self._field = field
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self):
        return number(self.status.get(self._field))


class HistoryCount(PileEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator, "history_count", "账号充电记录数")

    @property
    def native_value(self):
        count = self.coordinator.data.get("account_record_count")
        return int(count) if count is not None else None

    @property
    def extra_state_attributes(self):
        return {"recent_records_for_this_charger": len(self.coordinator.data.get("recent_records", []))}


class FaultCode(PileEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator, "fault", "故障代码")

    @property
    def native_value(self):
        return self.status.get("faultCode") or "无"
