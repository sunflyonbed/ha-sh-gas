#!/usr/bin/env python3
"""Query Shanghai Gas directly and print Home Assistant-like entities.

This script is intentionally standalone and only uses the Python standard
library, so it can validate the captured upstream API without Home Assistant.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import gzip
import json
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://mpshgas.huaqi-it.com.cn"
ORIGIN = "MiniPro"
TIMEOUT = 20

QUERY_BILLS_PATH = "/v1/accountingService/queryBills"


class ShGasCliError(Exception):
    """Raised when the CLI cannot complete the request."""


@dataclass(frozen=True)
class InputData:
    """User input required by the Shanghai Gas API."""

    token: str
    customer_id: str
    company_code: str


@dataclass(frozen=True)
class GasAccount:
    """A Shanghai Gas account returned by login."""

    customer_id: str
    company_code: str
    account_id: str | None
    account_code: str | None
    customer_name: str | None
    customer_address: str | None
    dept: str | None
    gas_class: str | None


@dataclass(frozen=True)
class AuthInfo:
    """Authenticated session state."""

    token: str
    account: GasAccount


@dataclass(frozen=True)
class GasBill:
    """One normalized gas bill record."""

    period: str
    period_date: str | None
    amount: float | None
    overdue_fine: float | None
    consumption: float | None
    year_consumption: float | None
    price: float | None
    last_reading: float | None
    current_reading: float | None
    payment_status: str | None
    billing_date: str | None
    read_date: str | None
    next_read_date: str | None


@dataclass(frozen=True)
class GasData:
    """Normalized gas data for one account."""

    bills: list[GasBill]
    balance: float | None
    pending_amount: float | None
    pending_overdue_fine: float | None
    next_read_date: str | None
    month_consumption: dict[str, float]
    first_price: float | None
    second_price: float | None
    third_price: float | None
    first_limit: float | None
    second_limit: float | None


def main() -> int:
    """Run the direct API check."""
    try:
        input_data = read_input()
        auth = AuthInfo(
            token=input_data.token,
            account=GasAccount(
                customer_id=input_data.customer_id,
                company_code=input_data.company_code,
                account_id=None,
                account_code=None,
                customer_name=None,
                customer_address=None,
                dept=None,
                gas_class=None,
            ),
        )
        gas_data = query_bills(input_data.customer_id, auth)
        output = build_output(input_data.customer_id, auth, gas_data)
    except ShGasCliError as err:
        print(
            json.dumps(
                {"ok": False, "error": str(err)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def read_input() -> InputData:
    """Read token/customer_id/company_code from stdin JSON or prompts."""
    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as err:
                raise ShGasCliError(f"stdin 不是有效 JSON: {err}") from err
            return InputData(
                token=required_str(data, "token"),
                customer_id=required_str(data, "customer_id", "customerId", "户号"),
                company_code=optional_str(data.get("company_code"))
                or optional_str(data.get("companyCode"))
                or "DZ",
            )
        raise ShGasCliError("stdin 为空；请交互输入或传入 JSON")

    token = input("token: ").strip()
    customer_id = input("户号 customer_id: ").strip()
    company_code = input("companyCode [DZ]: ").strip() or "DZ"
    if not token or not customer_id:
        raise ShGasCliError("token 和 customer_id 都不能为空")
    return InputData(
        token=token,
        customer_id=customer_id,
        company_code=company_code,
    )


def query_bills(customer_id: str, auth: AuthInfo) -> GasData:
    """Query gas bills for one account."""
    payload = {
        "companyCode": auth.account.company_code,
        "customerId": customer_id,
        "origin": ORIGIN,
        "timestamp": timestamp_ms(),
    }
    data = post_json(QUERY_BILLS_PATH, payload, token=auth.token)

    raw_bills = data.get("bills")
    if not isinstance(raw_bills, list):
        raise ShGasCliError("账单响应缺少 bills 数组")

    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    ext = result.get("gasBillExt") if isinstance(result.get("gasBillExt"), dict) else {}

    return GasData(
        bills=[parse_bill(item) for item in raw_bills if isinstance(item, dict)],
        balance=parse_float(ext.get("balance")),
        pending_amount=parse_float(ext.get("money")),
        pending_overdue_fine=parse_float(ext.get("overdueFine")),
        next_read_date=parse_date(ext.get("nextReadDate")),
        month_consumption=parse_month_consumption(result.get("monthConsumption")),
        first_price=parse_float(result.get("firstPrice")),
        second_price=parse_float(result.get("secondPrice")),
        third_price=parse_float(result.get("thirdPrice")),
        first_limit=parse_float(result.get("firstLimit")),
        second_limit=parse_float(result.get("secondLimit")),
    )


def post_json(
    path: str,
    payload: dict[str, Any],
    *,
    token: str | None,
) -> dict[str, Any]:
    """POST JSON to the Shanghai Gas API."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 "
            "MicroMessenger/7.0.20 MiniProgramEnv/Windows"
        ),
        "xweb_xhr": "1",
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "*/*",
        "Referer": "https://servicewechat.com/wx037f99c4619a13bd/40/page-frame.html",
    }
    if token:
        headers["token"] = token

    request = Request(
        f"{BASE_URL}{path}",
        data=body,
        method="POST",
        headers=headers,
    )

    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            response_body = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                response_body = gzip.decompress(response_body)
    except HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise ShGasCliError(f"HTTP {err.code}: {detail}") from err
    except URLError as err:
        raise ShGasCliError(f"网络请求失败: {err.reason}") from err
    except TimeoutError as err:
        raise ShGasCliError("网络请求超时") from err
    except OSError as err:
        raise ShGasCliError(f"响应解压失败: {err}") from err

    try:
        data = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ShGasCliError("接口返回不是有效 JSON") from err

    if not isinstance(data, dict):
        raise ShGasCliError("接口返回不是 JSON 对象")

    if data.get("resultCode") != "0000":
        msg = (
            data.get("resultInfo")
            if isinstance(data.get("resultInfo"), str)
            else "请求失败"
        )
        raise ShGasCliError(f"{msg}，resultCode={data.get('resultCode')}")

    return data


def find_account(accounts: list[Any], customer_id: str) -> GasAccount | None:
    """Find account details by customer id."""
    for item in accounts:
        if not isinstance(item, dict):
            continue
        candidates = {
            optional_str(item.get("customerId")),
            optional_str(item.get("accountId")),
            optional_str(item.get("recordId")),
        }
        if customer_id not in candidates:
            continue

        company_code = optional_str(item.get("companyCode"))
        if company_code is None:
            raise ShGasCliError("匹配到户号，但缺少 companyCode")

        return GasAccount(
            customer_id=customer_id,
            company_code=company_code,
            account_id=optional_str(item.get("accountId")),
            account_code=optional_str(item.get("accountCode")),
            customer_name=optional_str(item.get("customerName")),
            customer_address=optional_str(item.get("customerAddress")),
            dept=optional_str(item.get("dept")),
            gas_class=optional_str(item.get("gasClass")),
        )
    return None


def parse_bill(raw: dict[str, Any]) -> GasBill:
    """Normalize one captured gas bill."""
    period = optional_str(raw.get("billYM")) or format_period(
        raw.get("year"),
        raw.get("month"),
    )
    return GasBill(
        period=period,
        period_date=parse_period(period),
        amount=parse_float(raw.get("money")),
        overdue_fine=parse_float(raw.get("overdueFine")),
        consumption=parse_float(raw.get("consumption")),
        year_consumption=parse_float(raw.get("yearConsumption")),
        price=parse_float(raw.get("price")),
        last_reading=parse_float(raw.get("lastReading")),
        current_reading=parse_float(raw.get("currentReading")),
        payment_status=optional_str(raw.get("paymentStatus")),
        billing_date=parse_date(raw.get("billingDate")),
        read_date=parse_date(raw.get("readDate")),
        next_read_date=parse_date(raw.get("nextReadDate")),
    )


def build_output(customer_id: str, auth: AuthInfo, gas_data: GasData) -> dict[str, Any]:
    """Build Home Assistant-like entity output."""
    suffix = customer_id[-4:] if len(customer_id) >= 4 else customer_id
    latest = gas_data.bills[0] if gas_data.bills else None
    history = [asdict(bill) for bill in gas_data.bills]

    return {
        "ok": True,
        "auth": {
            "token": mask(auth.token),
        },
        "account": {
            "customer_id": mask(customer_id),
            "company_code": auth.account.company_code,
            "account_id": mask(auth.account.account_id),
            "account_code": mask(auth.account.account_code),
            "customer_name": mask(auth.account.customer_name),
            "customer_address": mask(auth.account.customer_address),
            "dept": auth.account.dept,
            "gas_class": auth.account.gas_class,
        },
        "device": {
            "identifiers": [["sh_gas", mask(customer_id)]],
            "name": f"上海燃气 {suffix}",
            "manufacturer": "Shanghai Gas",
            "model": auth.account.gas_class,
        },
        "entities": [
            {
                "unique_id": f"{suffix}_latest_consumption",
                "name": "本次用气量",
                "state": latest.consumption if latest else None,
                "unit": "m³",
                "device_class": "gas",
                "state_class": "measurement",
            },
            {
                "unique_id": f"{suffix}_latest_amount",
                "name": "最近账单金额",
                "state": latest.amount if latest else None,
                "unit": "CNY",
                "device_class": "monetary",
                "state_class": "measurement",
                "attributes": {
                    "period": latest.period if latest else None,
                    "payment_status": latest.payment_status if latest else None,
                    "bill_count": len(gas_data.bills),
                    "month_consumption": gas_data.month_consumption,
                    "history": history,
                },
            },
            {
                "unique_id": f"{suffix}_balance",
                "name": "余额",
                "state": gas_data.balance,
                "unit": "CNY",
                "device_class": "monetary",
                "state_class": "measurement",
            },
            {
                "unique_id": f"{suffix}_pending_amount",
                "name": "待缴金额",
                "state": gas_data.pending_amount,
                "unit": "CNY",
                "device_class": "monetary",
                "state_class": "measurement",
            },
            {
                "unique_id": f"{suffix}_current_reading",
                "name": "本次抄表读数",
                "state": latest.current_reading if latest else None,
                "unit": "m³",
                "device_class": "gas",
                "state_class": "total_increasing",
            },
            {
                "unique_id": f"{suffix}_latest_period",
                "name": "最近账期",
                "state": latest.period_date if latest else None,
                "device_class": "date",
            },
            {
                "unique_id": f"{suffix}_next_read_date",
                "name": "下次抄表日期",
                "state": gas_data.next_read_date
                or (latest.next_read_date if latest else None),
                "device_class": "date",
            },
        ],
        "tariff": {
            "first_price": gas_data.first_price,
            "second_price": gas_data.second_price,
            "third_price": gas_data.third_price,
            "first_limit": gas_data.first_limit,
            "second_limit": gas_data.second_limit,
        },
        "bills": history,
    }


def required_str(data: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty string field from data."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    joined = " / ".join(keys)
    raise ShGasCliError(f"缺少必填字段: {joined}")


def optional_str(value: Any) -> str | None:
    """Return a non-empty string or None."""
    if isinstance(value, str) and value:
        return value
    return None


def parse_float(value: Any) -> float | None:
    """Parse a float from upstream data."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_month_consumption(value: Any) -> dict[str, float]:
    """Parse the monthConsumption object."""
    if not isinstance(value, dict):
        return {}
    parsed: dict[str, float] = {}
    for period, consumption in value.items():
        amount = parse_float(consumption)
        if isinstance(period, str) and amount is not None:
            parsed[period] = amount
    return parsed


def format_period(year: Any, month: Any) -> str:
    """Format numeric year/month fields as YYYY-MM."""
    year_float = parse_float(year)
    month_float = parse_float(month)
    if year_float is None or month_float is None:
        return ""
    return f"{int(year_float):04d}-{int(month_float):02d}"


def parse_period(value: str) -> str | None:
    """Parse YYYY-MM to an ISO date string."""
    if not value:
        return None
    try:
        return date.fromisoformat(f"{value}-01").isoformat()
    except ValueError:
        return None


def parse_date(value: Any) -> str | None:
    """Parse an upstream datetime value to an ISO date string."""
    text = optional_str(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date().isoformat()
    except ValueError:
        return None


def mask(value: str | None) -> str | None:
    """Mask a sensitive value for console output."""
    if value is None:
        return None
    if len(value) <= 4:
        return "*" * len(value)
    if len(value) <= 8:
        return f"{value[:2]}***{value[-2:]}"
    return f"{value[:4]}***{value[-4:]}"


def timestamp_ms() -> int:
    """Return current Unix timestamp in milliseconds."""
    return int(time.time() * 1000)


if __name__ == "__main__":
    raise SystemExit(main())
