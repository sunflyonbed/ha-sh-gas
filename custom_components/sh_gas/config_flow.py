"""Config flow for the Shanghai Gas integration."""

from __future__ import annotations

from typing import Any

from aiohttp import ClientSession
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    ShanghaiGasClient,
    ShGasApiError,
    ShGasAuthError,
    ShGasConnectionError,
)
from .const import (
    CONF_COMPANY_CODE,
    CONF_CUSTOMER_ID,
    CONF_TOKEN,
    DEFAULT_COMPANY_CODE,
    DOMAIN,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CUSTOMER_ID): str,
        vol.Required(CONF_TOKEN): str,
        vol.Optional(CONF_COMPANY_CODE, default=DEFAULT_COMPANY_CODE): str,
    }
)


async def validate_input(
    session: ClientSession,
    data: dict[str, Any],
) -> dict[str, str]:
    """Validate the user input allows us to connect."""
    customer_id = str(data[CONF_CUSTOMER_ID]).strip()
    token = str(data[CONF_TOKEN]).strip()
    company_code = (
        str(data.get(CONF_COMPANY_CODE, DEFAULT_COMPANY_CODE)).strip()
        or DEFAULT_COMPANY_CODE
    )
    if not customer_id or not token:
        raise ShGasAuthError("Missing token or customer id")

    client = ShanghaiGasClient(
        session=session,
        token=token,
        customer_id=customer_id,
        company_code=company_code,
    )
    await client.async_get_bills()

    return {
        CONF_CUSTOMER_ID: customer_id,
        CONF_TOKEN: token,
        CONF_COMPANY_CODE: company_code,
    }


class ShGasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Shanghai Gas."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            customer_id = str(user_input[CONF_CUSTOMER_ID]).strip()
            await self.async_set_unique_id(customer_id)
            self._abort_if_unique_id_configured()

            try:
                entry_data = await validate_input(
                    async_get_clientsession(self.hass),
                    user_input,
                )
            except ShGasAuthError:
                errors["base"] = "invalid_auth"
            except ShGasConnectionError:
                errors["base"] = "cannot_connect"
            except ShGasApiError:
                errors["base"] = "unknown"
            else:
                title = (
                    f"上海燃气 {customer_id[-4:]}"
                    if len(customer_id) >= 4
                    else "上海燃气"
                )
                return self.async_create_entry(
                    title=title,
                    data=entry_data,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
