"""Data coordinator for the Shanghai Gas integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GasData, ShanghaiGasClient, ShGasConnectionError, ShGasError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class ShGasDataUpdateCoordinator(DataUpdateCoordinator[GasData]):
    """Fetch Shanghai Gas account data at a controlled interval."""

    def __init__(self, hass: HomeAssistant, client: ShanghaiGasClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> GasData:
        """Fetch data from Shanghai Gas."""
        try:
            return await self.client.async_refresh()
        except ShGasConnectionError as err:
            raise UpdateFailed(str(err)) from err
        except ShGasError as err:
            raise UpdateFailed(str(err)) from err
