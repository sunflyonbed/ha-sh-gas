"""Base entity for the Shanghai Gas integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ShGasDataUpdateCoordinator


class ShGasEntity(CoordinatorEntity[ShGasDataUpdateCoordinator]):
    """Base Shanghai Gas entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ShGasDataUpdateCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._customer_id = coordinator.client.customer_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for this account."""
        suffix = (
            self._customer_id[-4:]
            if len(self._customer_id) >= 4
            else self._customer_id
        )
        data = self.coordinator.data
        model = data.account.gas_class if data is not None else None
        return DeviceInfo(
            identifiers={(DOMAIN, self._customer_id)},
            name=f"上海燃气 {suffix}",
            manufacturer="Shanghai Gas",
            model=model,
        )
