"""Sensors for the Shanghai Gas integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .api import GasData
from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import ShGasDataUpdateCoordinator
from .entity import ShGasEntity


@dataclass(frozen=True, kw_only=True)
class ShGasSensorEntityDescription(SensorEntityDescription):
    """Describe a Shanghai Gas sensor."""

    value_fn: Callable[[GasData], StateType | date | None]
    attributes_fn: Callable[[GasData], dict[str, Any]] | None = None


SENSOR_DESCRIPTIONS: tuple[ShGasSensorEntityDescription, ...] = (
    ShGasSensorEntityDescription(
        key="latest_consumption",
        translation_key="latest_consumption",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.latest.consumption if data.latest else None,
    ),
    ShGasSensorEntityDescription(
        key="latest_amount",
        translation_key="latest_amount",
        native_unit_of_measurement="CNY",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.latest.amount if data.latest else None,
        attributes_fn=lambda data: {
            "history": _history_attributes(data),
            "month_consumption": data.month_consumption,
        },
    ),
    ShGasSensorEntityDescription(
        key="balance",
        translation_key="balance",
        native_unit_of_measurement="CNY",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.balance,
    ),
    ShGasSensorEntityDescription(
        key="pending_amount",
        translation_key="pending_amount",
        native_unit_of_measurement="CNY",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.pending_amount,
    ),
    ShGasSensorEntityDescription(
        key="current_reading",
        translation_key="current_reading",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.latest.current_reading if data.latest else None,
    ),
    ShGasSensorEntityDescription(
        key="latest_period",
        translation_key="latest_period",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda data: data.latest.period_date if data.latest else None,
    ),
    ShGasSensorEntityDescription(
        key="next_read_date",
        translation_key="next_read_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda data: (
            data.next_read_date
            if data.next_read_date is not None
            else data.latest.next_read_date
            if data.latest
            else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Shanghai Gas sensors from a config entry."""
    coordinator: ShGasDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    async_add_entities(
        ShGasSensor(coordinator, description) for description in SENSOR_DESCRIPTIONS
    )


class ShGasSensor(ShGasEntity, SensorEntity):
    """Shanghai Gas sensor."""

    entity_description: ShGasSensorEntityDescription

    def __init__(
        self,
        coordinator: ShGasDataUpdateCoordinator,
        description: ShGasSensorEntityDescription,
    ) -> None:
        """Initialize a Shanghai Gas sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self._customer_id}_{description.key}"

    @property
    def native_value(self) -> StateType | date | None:
        """Return the native sensor value."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return sanitized extra state attributes."""
        if (
            self.coordinator.data is None
            or self.entity_description.attributes_fn is None
        ):
            return None
        attrs = self.entity_description.attributes_fn(self.coordinator.data)
        if self.coordinator.data.latest is not None:
            attrs["period"] = self.coordinator.data.latest.period
            attrs["payment_status"] = self.coordinator.data.latest.payment_status
        attrs["bill_count"] = len(self.coordinator.data.bills)
        return attrs


def _history_attributes(data: GasData) -> list[dict[str, Any]]:
    return [
        {
            "period": bill.period,
            "amount": bill.amount,
            "overdue_fine": bill.overdue_fine,
            "consumption": bill.consumption,
            "year_consumption": bill.year_consumption,
            "price": bill.price,
            "last_reading": bill.last_reading,
            "current_reading": bill.current_reading,
            "read_date": bill.read_date.isoformat() if bill.read_date else None,
            "next_read_date": (
                bill.next_read_date.isoformat() if bill.next_read_date else None
            ),
            "payment_status": bill.payment_status,
        }
        for bill in data.bills
    ]
