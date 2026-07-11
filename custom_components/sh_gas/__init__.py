"""Shanghai Gas integration."""

from __future__ import annotations

from typing import Any

from .const import (
    CONF_COMPANY_CODE,
    CONF_CUSTOMER_ID,
    CONF_MOBILE,
    CONF_PASSWORD_HASH,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DEFAULT_COMPANY_CODE,
    DOMAIN,
    PLATFORMS,
)


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    """Set up Shanghai Gas from a config entry."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .api import ShanghaiGasClient
    from .coordinator import ShGasDataUpdateCoordinator

    session = async_get_clientsession(hass)
    client = ShanghaiGasClient(
        session=session,
        customer_id=str(entry.data[CONF_CUSTOMER_ID]),
        company_code=str(entry.data.get(CONF_COMPANY_CODE, DEFAULT_COMPANY_CODE)),
        mobile=str(entry.data.get(CONF_MOBILE) or "") or None,
        password_hash=str(entry.data.get(CONF_PASSWORD_HASH) or "") or None,
    )
    coordinator = ShGasDataUpdateCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_CLIENT: client,
        DATA_COORDINATOR: coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload a Shanghai Gas config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unload_ok
