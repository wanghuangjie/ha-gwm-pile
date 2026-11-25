"""Common entity identity for a GWM charger."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class PileEntity(CoordinatorEntity):
    """Attach the entity to its physical charger."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, key, name):
        super().__init__(coordinator)
        code = coordinator.client.pile_code
        self._attr_unique_id = f"{code}_{key}"
        self._attr_suggested_object_id = f"{DOMAIN}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, code)}, manufacturer="长城汽车", name="长城家充桩",
        )

    @property
    def status(self):
        return self.coordinator.data["status"]
