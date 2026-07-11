"""Config flow for the Shanghai Gas integration."""

from __future__ import annotations

from typing import Any

from aiohttp import ClientSession
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    ShanghaiGasClient,
    ShGasApiError,
    ShGasAuthError,
    ShGasConnectionError,
    _password_hash,
)
from .const import (
    CONF_COMPANY_CODE,
    CONF_CUSTOMER_ID,
    CONF_MOBILE,
    CONF_PASSWORD,
    CONF_PASSWORD_HASH,
    DEFAULT_COMPANY_CODE,
    DOMAIN,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CUSTOMER_ID): str,
        vol.Required(CONF_MOBILE): str,
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
        vol.Optional(CONF_COMPANY_CODE, default=DEFAULT_COMPANY_CODE): str,
    }
)


def _reauth_schema(company_code: str) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_MOBILE): str,
            vol.Required(CONF_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_COMPANY_CODE, default=company_code): str,
        }
    )


async def validate_input(
    session: ClientSession,
    data: dict[str, Any],
) -> dict[str, str]:
    """Validate the user input allows us to connect."""
    customer_id = str(data[CONF_CUSTOMER_ID]).strip()
    mobile = str(data[CONF_MOBILE]).strip()
    password_hash = _password_hash(str(data[CONF_PASSWORD]))
    company_code = (
        str(data.get(CONF_COMPANY_CODE, DEFAULT_COMPANY_CODE)).strip()
        or DEFAULT_COMPANY_CODE
    )
    if not customer_id or not mobile:
        raise ShGasAuthError("Missing mobile or customer id")

    client = ShanghaiGasClient(
        session=session,
        customer_id=customer_id,
        company_code=company_code,
        mobile=mobile,
        password_hash=password_hash,
    )
    await client.async_login()
    await client.async_get_bills()

    return {
        CONF_CUSTOMER_ID: customer_id,
        CONF_MOBILE: mobile,
        CONF_PASSWORD_HASH: password_hash,
        CONF_COMPANY_CODE: client.account.company_code,
    }


class ShGasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Shanghai Gas."""

    VERSION = 1
    _reauth_data: dict[str, Any] | None = None

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

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> config_entries.ConfigFlowResult:
        """Handle reauth when the stored credentials can no longer be used."""
        self._reauth_data = entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Collect credentials for reauthentication."""
        if self._reauth_data is None:
            return self.async_abort(reason="unknown")

        errors: dict[str, str] = {}
        customer_id = str(self._reauth_data[CONF_CUSTOMER_ID])
        company_code = str(
            self._reauth_data.get(CONF_COMPANY_CODE, DEFAULT_COMPANY_CODE)
        )

        if user_input is not None:
            try:
                entry_data = await validate_input(
                    async_get_clientsession(self.hass),
                    {
                        **user_input,
                        CONF_CUSTOMER_ID: customer_id,
                    },
                )
            except ShGasAuthError:
                errors["base"] = "invalid_auth"
            except ShGasConnectionError:
                errors["base"] = "cannot_connect"
            except ShGasApiError:
                errors["base"] = "unknown"
            else:
                entry = self.hass.config_entries.async_get_entry(
                    self.context["entry_id"]
                )
                if entry is None:
                    return self.async_abort(reason="unknown")

                self.hass.config_entries.async_update_entry(entry, data=entry_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_reauth_schema(company_code),
            errors=errors,
        )
