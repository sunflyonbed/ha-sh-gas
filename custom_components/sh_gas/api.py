"""Shanghai Gas API client."""

from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
import hashlib
import logging
import re
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiohttp import ClientSession

from .const import BASE_URL, ORIGIN, PC_ORIGIN, WEB_API_BASE_URL

_LOGGER = logging.getLogger(__name__)

GET_CAPTCHA_PATH = "/v1/thirdparty/common/img/getImgAuthCode"
LOGIN_PATH = "/v1/user/common/doLogin"
QUERY_BILLS_PATH = "/v1/accountingService/queryBills"
REQUEST_TIMEOUT = 20
CAPTCHA_RETRIES = 3


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
        customer_id: str,
        company_code: str,
        mobile: str | None = None,
        password_hash: str | None = None,
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self._token: str | None = None
        self._customer_id = customer_id
        self._mobile = mobile or None
        self._password_hash = password_hash or None
        self._account = GasAccount(
            customer_id=customer_id,
            company_code=company_code,
        )

    @property
    def customer_id(self) -> str:
        """Return the configured gas account id."""
        return self._customer_id

    @property
    def token(self) -> str | None:
        """Return the current API token."""
        return self._token

    @property
    def account(self) -> GasAccount:
        """Return the current gas account details."""
        return self._account

    async def async_get_bills(self) -> GasData:
        """Fetch gas usage and billing records."""
        if not self._token:
            await self.async_login()

        try:
            data = await self._async_bill_request()
        except ShGasAuthError:
            if not self._can_login:
                raise
            await self.async_login()
            data = await self._async_bill_request()

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

    async def async_login(self) -> None:
        """Login with mobile/password and update the current token."""
        if not self._can_login:
            raise ShGasAuthError("Missing mobile or password")

        last_error: ShGasError | None = None
        for attempt in range(CAPTCHA_RETRIES):
            try:
                captcha = await self._async_get_captcha()
                code = await self._async_recognize_captcha(
                    captcha["base64_image"],
                )
                await self._async_password_login(captcha["imgid"], code)
                return
            except (ShGasAuthError, ShGasApiError) as err:
                last_error = err
                _LOGGER.debug("Shanghai Gas login attempt %s failed", attempt + 1)

        if last_error is not None:
            raise last_error
        raise ShGasAuthError("Shanghai Gas login failed")

    @property
    def _can_login(self) -> bool:
        return bool(self._mobile and self._password_hash)

    async def _async_get_captcha(self) -> dict[str, str]:
        payload = {"timestamp": _timestamp_ms()}
        data = await self._async_request(
            WEB_API_BASE_URL,
            GET_CAPTCHA_PATH,
            payload,
            token="",
            method="GET",
            headers=_pc_headers(),
        )

        imgid = _expect_str(data.get("imgid"), "imgid")
        base64_image = _expect_str(data.get("base64Image"), "base64Image")
        return {"imgid": imgid, "base64_image": base64_image}

    async def _async_recognize_captcha(self, base64_image: str) -> str:
        try:
            image = _decode_base64_image(base64_image)
        except ValueError as err:
            raise ShGasApiError("Shanghai Gas returned invalid captcha image") from err

        loop = asyncio.get_running_loop()
        code = await loop.run_in_executor(None, _recognize_captcha_sync, image)
        normalized = _normalize_captcha_code(code)
        if normalized is None:
            raise ShGasAuthError("Failed to recognize captcha")
        return normalized

    async def _async_password_login(self, imgid: str, img_auth_code: str) -> None:
        payload = {
            "mobile": self._mobile,
            "method": "PWD",
            "pwd": self._password_hash,
            "smsAuthCode": "",
            "imgid": imgid,
            "imgAuthCode": img_auth_code,
            "qrCode": "",
            "origin": PC_ORIGIN,
            "timestamp": _timestamp_ms(),
        }
        data = await self._async_request(
            WEB_API_BASE_URL,
            LOGIN_PATH,
            payload,
            token="",
            headers=_pc_headers(),
        )

        token = _expect_str(data.get("token"), "token")
        accounts = data.get("accountList")
        if not isinstance(accounts, list):
            raise ShGasAuthError("Missing account list")

        account = _find_account(accounts, self._customer_id)
        if account is None:
            raise ShGasAuthError("Configured customer id is not bound to this account")

        self._token = token
        self._account = account

    async def _async_bill_request(self) -> dict[str, Any]:
        payload = {
            "companyCode": self._account.company_code,
            "customerId": self._customer_id,
            "origin": ORIGIN,
            "timestamp": _timestamp_ms(),
        }
        return await self._async_request(
            BASE_URL,
            QUERY_BILLS_PATH,
            payload,
            token=self._token,
            headers=_mini_program_headers(),
        )

    async def _async_request(
        self,
        base_url: str,
        path: str,
        payload: dict[str, Any],
        *,
        token: str | None,
        headers: dict[str, str],
        method: str = "POST",
    ) -> dict[str, Any]:
        url = f"{base_url}{path}"
        request_headers = dict(headers)
        if token is not None:
            request_headers["token"] = token

        try:
            from aiohttp import ClientError, ClientResponseError

            async with asyncio.timeout(REQUEST_TIMEOUT):
                if method == "GET":
                    async with self._session.get(
                        url,
                        params=payload,
                        headers=request_headers,
                    ) as response:
                        response.raise_for_status()
                        data = await response.json(content_type=None)
                else:
                    async with self._session.post(
                        url,
                        json=payload,
                        headers=request_headers,
                    ) as response:
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
            if path == LOGIN_PATH:
                raise ShGasAuthError(message)
            if code in {"401", "403", "1001", "1002", "2001"}:
                raise ShGasAuthError(message)
            raise ShGasApiError(message)

        return data


def _mini_program_headers() -> dict[str, str]:
    return {
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 "
            "MicroMessenger/7.0.20 MiniProgramEnv/Windows"
        ),
        "xweb_xhr": "1",
        "content-type": "application/json;charset=UTF-8",
        "accept": "*/*",
        "referer": "https://servicewechat.com/wx037f99c4619a13bd/40/page-frame.html",
    }


def _pc_headers() -> dict[str, str]:
    return {
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
        ),
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://www.shgas.com.cn",
        "referer": "https://www.shgas.com.cn/",
    }


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


def _password_hash(password: str) -> str:
    password = password.strip()
    if not password:
        raise ShGasAuthError("Missing password")
    if re.fullmatch(r"[0-9a-fA-F]{32}", password):
        return password.lower()
    return hashlib.md5(password.encode()).hexdigest()


def _decode_base64_image(value: str) -> bytes:
    if "," in value:
        value = value.split(",", 1)[1]
    try:
        return base64.b64decode(value)
    except binascii.Error as err:
        raise ValueError("Invalid base64 image") from err


@lru_cache(maxsize=1)
def _captcha_ocr() -> Any:
    try:
        import ddddocr
    except ImportError as err:
        raise ShGasAuthError("ddddocr is not installed") from err

    return ddddocr.DdddOcr(show_ad=False)


def _recognize_captcha_sync(image: bytes) -> str:
    result = _captcha_ocr().classification(image)
    if not isinstance(result, str):
        raise ShGasAuthError("ddddocr returned an invalid result")
    return result


def _normalize_captcha_code(value: str) -> str | None:
    normalized = "".join(ch for ch in value.upper() if ch.isalnum())
    if len(normalized) != 4:
        return None
    return normalized


def _timestamp_ms() -> int:
    return int(time.time() * 1000)
