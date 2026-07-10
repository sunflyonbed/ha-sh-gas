"""Shanghai Gas API client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiohttp import ClientSession

from .const import BASE_URL, ORIGIN

_LOGGER = logging.getLogger(__name__)

QUERY_BILLS_PATH = "/v1/accountingService/queryBills"
REQUEST_TIMEOUT = 20


class ShGasError(Exception):
    """Base exception for Shanghai Gas errors."""


class ShGasAuthError(ShGasError):
    """Raised when authentication fails."""


class ShGasApiError(ShGasError):
    """Raised when the upstream API returns an error."""


class ShGasConnectionError(ShGasError):
    """Raised when the upstream API cannot be reached."""


@dataclass(slots=True, frozen=True)
class GasAccount:
    """A Shanghai Gas account returned by login."""

    customer_id: str
    company_code: str
    account_id: str | None = None
    account_code: str | None = None
    customer_name: str | None = None
    customer_address: str | None = None
    dept: str | None = None
    gas_class: str | None = None


@dataclass(slots=True, frozen=True)
class GasBill:
    """A single Shanghai Gas billing or usage record."""

    period: str
    period_date: date | None
    amount: float | None
    overdue_fine: float | None
    consumption: float | None
    year_consumption: float | None
    price: float | None
    last_reading: float | None
    current_reading: float | None
    payment_status: str | None
    billing_date: date | None
    read_date: date | None
    next_read_date: date | None


@dataclass(slots=True, frozen=True)
class GasData:
    """Normalized gas data for one account."""

    customer_id: str
    account: GasAccount
    bills: tuple[GasBill, ...]
    balance: float | None
    pending_amount: float | None
    pending_overdue_fine: float | None
    next_read_date: date | None
    month_consumption: dict[str, float]
    first_price: float | None
    second_price: float | None
    third_price: float | None
    first_limit: float | None
    second_limit: float | None

    @property
    def latest(self) -> GasBill | None:
        """Return the latest bill reported by the API."""
        return self.bills[0] if self.bills else None


class ShanghaiGasClient:
    """Async client for the Shanghai Gas mini-program API."""

    def __init__(
        self,
        session: ClientSession,
        token: str,
        customer_id: str,
        company_code: str,
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self._token = token
        self._customer_id = customer_id
        self._account = GasAccount(
            customer_id=customer_id,
            company_code=company_code,
        )

    @property
    def customer_id(self) -> str:
        """Return the configured gas account id."""
        return self._customer_id

    async def async_get_bills(self) -> GasData:
        """Fetch gas usage and billing records."""
        payload = {
            "companyCode": self._account.company_code,
            "customerId": self._customer_id,
            "origin": ORIGIN,
            "timestamp": _timestamp_ms(),
        }
        data = await self._async_request(
            QUERY_BILLS_PATH,
            payload,
            token=self._token,
        )

        raw_bills = data.get("bills")
        if not isinstance(raw_bills, list):
            raise ShGasApiError("Unexpected gas bills response")

        result = data.get("result")
        if not isinstance(result, dict):
            result = {}

        ext = result.get("gasBillExt")
        if not isinstance(ext, dict):
            ext = {}

        return GasData(
            customer_id=self._customer_id,
            account=self._account,
            bills=tuple(
                _parse_bill(item) for item in raw_bills if isinstance(item, dict)
            ),
            balance=_parse_float(ext.get("balance")),
            pending_amount=_parse_float(ext.get("money")),
            pending_overdue_fine=_parse_float(ext.get("overdueFine")),
            next_read_date=_parse_date(ext.get("nextReadDate")),
            month_consumption=_parse_month_consumption(result.get("monthConsumption")),
            first_price=_parse_float(result.get("firstPrice")),
            second_price=_parse_float(result.get("secondPrice")),
            third_price=_parse_float(result.get("thirdPrice")),
            first_limit=_parse_float(result.get("firstLimit")),
            second_limit=_parse_float(result.get("secondLimit")),
        )

    async def async_refresh(self) -> GasData:
        """Refresh account data with the configured token."""
        return await self.async_get_bills()

    async def _async_request(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        token: str | None,
    ) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        headers = {
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 "
                "MicroMessenger/7.0.20 MiniProgramEnv/Windows"
            ),
            "xweb_xhr": "1",
            "content-type": "application/json;charset=UTF-8",
            "accept": "*/*",
            "referer": (
                "https://servicewechat.com/wx037f99c4619a13bd/40/page-frame.html"
            ),
        }
        if token:
            headers["token"] = token

        try:
            from aiohttp import ClientError, ClientResponseError

            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await self._session.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = await response.json(content_type=None)
        except TimeoutError as err:
            raise ShGasConnectionError("Timed out connecting to Shanghai Gas") from err
        except (ClientResponseError, ClientError) as err:
            raise ShGasConnectionError("Error connecting to Shanghai Gas") from err
        except ValueError as err:
            raise ShGasApiError("Shanghai Gas returned invalid JSON") from err

        if not isinstance(data, dict):
            raise ShGasApiError("Shanghai Gas returned an unexpected response")

        code = data.get("resultCode")
        if code != "0000":
            message = (
                _optional_str(data.get("resultInfo"))
                or "Shanghai Gas request failed"
            )
            if code in {"401", "403", "1001", "1002", "2001"}:
                raise ShGasAuthError(message)
            raise ShGasApiError(message)

        return data


def _find_account(accounts: list[Any], customer_id: str) -> GasAccount | None:
    for item in accounts:
        if not isinstance(item, dict):
            continue
        candidates = {
            _optional_str(item.get("customerId")),
            _optional_str(item.get("accountId")),
            _optional_str(item.get("recordId")),
        }
        if customer_id not in candidates:
            continue
        company_code = _optional_str(item.get("companyCode"))
        if company_code is None:
            raise ShGasAuthError("Missing company code")
        return GasAccount(
            customer_id=customer_id,
            company_code=company_code,
            account_id=_optional_str(item.get("accountId")),
            account_code=_optional_str(item.get("accountCode")),
            customer_name=_optional_str(item.get("customerName")),
            customer_address=_optional_str(item.get("customerAddress")),
            dept=_optional_str(item.get("dept")),
            gas_class=_optional_str(item.get("gasClass")),
        )
    return None


def _parse_bill(raw: dict[str, Any]) -> GasBill:
    period = _optional_str(raw.get("billYM")) or _format_period(
        raw.get("year"),
        raw.get("month"),
    )
    return GasBill(
        period=period,
        period_date=_parse_period(period),
        amount=_parse_float(raw.get("money")),
        overdue_fine=_parse_float(raw.get("overdueFine")),
        consumption=_parse_float(raw.get("consumption")),
        year_consumption=_parse_float(raw.get("yearConsumption")),
        price=_parse_float(raw.get("price")),
        last_reading=_parse_float(raw.get("lastReading")),
        current_reading=_parse_float(raw.get("currentReading")),
        payment_status=_optional_str(raw.get("paymentStatus")),
        billing_date=_parse_date(raw.get("billingDate")),
        read_date=_parse_date(raw.get("readDate")),
        next_read_date=_parse_date(raw.get("nextReadDate")),
    )


def _format_period(year: Any, month: Any) -> str:
    year_float = _parse_float(year)
    month_float = _parse_float(month)
    if year_float is None or month_float is None:
        return ""
    return f"{int(year_float):04d}-{int(month_float):02d}"


def _parse_period(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m").date().replace(day=1)
    except ValueError:
        _LOGGER.debug("Invalid gas bill period: %s", value)
        return None


def _parse_date(value: Any) -> date | None:
    text = _optional_str(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        _LOGGER.debug("Invalid gas date: %s", text)
        return None


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_month_consumption(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    parsed: dict[str, float] = {}
    for period, consumption in value.items():
        amount = _parse_float(consumption)
        if isinstance(period, str) and amount is not None:
            parsed[period] = amount
    return parsed


def _expect_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ShGasAuthError(f"Missing {field}")
    return value


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _timestamp_ms() -> int:
    return int(time.time() * 1000)
