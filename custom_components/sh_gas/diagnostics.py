"""Diagnostics support for the Shanghai Gas integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_COMPANY_CODE,
    CONF_CUSTOMER_ID,
    CONF_MOBILE,
    CONF_OCR_API_URL,
    CONF_PASSWORD,
    CONF_PASSWORD_HASH,
)

TO_REDACT = {
    CONF_COMPANY_CODE,
    CONF_CUSTOMER_ID,
    CONF_MOBILE,
    CONF_OCR_API_URL,
    CONF_PASSWORD,
    CONF_PASSWORD_HASH,
    "account_code",
    "accountId",
    "account_id",
    "address",
    "customerAddress",
    "customerName",
    "customer_id",
    "mobile",
    "openid",
    "password",
    "password_hash",
    "qrcode",
    "qrCode",
    "token",
    "unionid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
    }
