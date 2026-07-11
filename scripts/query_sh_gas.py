#!/usr/bin/env python3
"""Query Shanghai Gas directly and print Home Assistant-like entities.

This script is intentionally standalone from Home Assistant. Password login
mode requires ddddocr for local image captcha recognition.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import asdict, dataclass
from datetime import date, datetime
from functools import lru_cache
from getpass import getpass
import gzip
import hashlib
import json
import re
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://mpshgas.huaqi-it.com.cn"
WEB_API_BASE_URL = "https://web-api.shgas.com.cn"
ORIGIN = "MiniPro"
PC_ORIGIN = "PC"
TIMEOUT = 20
CAPTCHA_RETRIES = 3

GET_CAPTCHA_PATH = "/v1/thirdparty/common/img/getImgAuthCode"
LOGIN_PATH = "/v1/user/common/doLogin"
QUERY_BILLS_PATH = "/v1/accountingService/queryBills"


class ShGasCliError(Exception):
    """Raised when the CLI cannot complete the request."""


@dataclass(frozen=True)
class InputData:
    """User input required by the Shanghai Gas API."""

    customer_id: str
    company_code: str
    mobile: str
    password: str


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
    method: str


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
        auth = authenticate(input_data)
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
    """Read login credentials from stdin JSON or prompts."""
    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as err:
                raise ShGasCliError(f"stdin 不是有效 JSON: {err}") from err
            return InputData(
                customer_id=required_str(data, "customer_id", "customerId", "户号"),
                company_code=optional_str(data.get("company_code"))
                or optional_str(data.get("companyCode"))
                or "DZ",
                mobile=required_str(data, "mobile", "phone", "手机号"),
                password=required_str(data, "password", "pwd", "密码"),
            )
        raise ShGasCliError("stdin 为空；请交互输入或传入 JSON")

    customer_id = input("户号 customer_id: ").strip()
    company_code = input("companyCode [DZ]: ").strip() or "DZ"
    mobile = input("手机号 mobile: ").strip()
    password = getpass("密码 password: ").strip()

    if not customer_id or not mobile or not password:
        raise ShGasCliError("customer_id、mobile 和 password 都不能为空")
    return InputData(
        customer_id=customer_id,
        company_code=company_code,
        mobile=mobile,
        password=password,
    )


def authenticate(input_data: InputData) -> AuthInfo:
    """Login with password captcha and build auth state."""
    password_hash_value = password_hash(input_data.password)
    last_error: ShGasCliError | None = None
    for attempt in range(CAPTCHA_RETRIES):
        try:
            captcha = get_captcha()
            img_auth_code = recognize_captcha(captcha["base64_image"])
            auth = login_with_password(
                mobile=input_data.mobile,
                password_hash_value=password_hash_value,
                customer_id=input_data.customer_id,
                fallback_company_code=input_data.company_code,
                imgid=captcha["imgid"],
                img_auth_code=img_auth_code,
            )
            print(
                f"验证码识别为 {img_auth_code}，第 {attempt + 1} 次登录成功",
                file=sys.stderr,
            )
            return auth
        except ShGasCliError as err:
            last_error = err
            print(f"第 {attempt + 1} 次登录失败: {err}", file=sys.stderr)

    if last_error is not None:
        raise last_error
    raise ShGasCliError("登录失败")


def get_captcha() -> dict[str, str]:
    """Fetch captcha image data."""
    data = request_json(
        WEB_API_BASE_URL,
        GET_CAPTCHA_PATH,
        {"timestamp": timestamp_ms()},
        token="",
        headers=pc_headers(),
        method="GET",
    )
    return {
        "imgid": required_str(data, "imgid"),
        "base64_image": required_str(data, "base64Image"),
    }


def recognize_captcha(base64_image: str) -> str:
    """Recognize a four-character captcha with local ddddocr."""
    image = decode_base64_image(base64_image)
    result = captcha_ocr().classification(image)
    if not isinstance(result, str):
        raise ShGasCliError("ddddocr 返回了无效结果")
    normalized = normalize_captcha_code(result)
    if normalized is None:
        raise ShGasCliError(f"验证码识别结果不是 4 位字符: {result!r}")
    return normalized


@lru_cache(maxsize=1)
def captcha_ocr() -> Any:
    """Create and cache the ddddocr model."""
    try:
        import ddddocr
    except ImportError as err:
        raise ShGasCliError(
            "缺少 ddddocr，请先运行: python3 -m pip install ddddocr==1.6.1"
        ) from err

    return ddddocr.DdddOcr(show_ad=False)


def login_with_password(
    *,
    mobile: str,
    password_hash_value: str,
    customer_id: str,
    fallback_company_code: str,
    imgid: str,
    img_auth_code: str,
) -> AuthInfo:
    """Login with mobile/password and captcha."""
    data = request_json(
        WEB_API_BASE_URL,
        LOGIN_PATH,
        {
            "mobile": mobile,
            "method": "PWD",
            "pwd": password_hash_value,
            "smsAuthCode": "",
            "imgid": imgid,
            "imgAuthCode": img_auth_code,
            "qrCode": "",
            "origin": PC_ORIGIN,
            "timestamp": timestamp_ms(),
        },
        token="",
        headers=pc_headers(),
    )

    token = required_str(data, "token")
    accounts = data.get("accountList")
    if not isinstance(accounts, list):
        raise ShGasCliError("登录响应缺少 accountList")

    account = find_account(accounts, customer_id)
    if account is None:
        raise ShGasCliError("登录成功，但该账号未绑定指定户号")

    if not account.company_code:
        account = GasAccount(
            customer_id=account.customer_id,
            company_code=fallback_company_code,
            account_id=account.account_id,
            account_code=account.account_code,
            customer_name=account.customer_name,
            customer_address=account.customer_address,
            dept=account.dept,
            gas_class=account.gas_class,
        )

    return AuthInfo(token=token, account=account, method="password")


def query_bills(customer_id: str, auth: AuthInfo) -> GasData:
    """Query gas bills for one account."""
    payload = {
        "companyCode": auth.account.company_code,
        "customerId": customer_id,
        "origin": ORIGIN,
        "timestamp": timestamp_ms(),
    }
    data = request_json(
        BASE_URL,
        QUERY_BILLS_PATH,
        payload,
        token=auth.token,
        headers=mini_program_headers(),
    )

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


def request_json(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    *,
    token: str | None,
    headers: dict[str, str],
    method: str = "POST",
) -> dict[str, Any]:
    """Send JSON API request to the Shanghai Gas API."""
    body = None
    url = f"{base_url}{path}"
    if method == "GET":
        url = f"{url}?{urlencode(payload)}"
    else:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request_headers = dict(headers)
    if token is not None:
        request_headers["token"] = token

    request = Request(
        url,
        data=body,
        method=method,
        headers=request_headers,
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


def mini_program_headers() -> dict[str, str]:
    """Return headers for the mini-program bill API."""
    return {
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


def pc_headers() -> dict[str, str]:
    """Return headers for the Shanghai Gas website API."""
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://www.shgas.com.cn",
        "Referer": "https://www.shgas.com.cn/",
    }


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
            "method": auth.method,
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


def password_hash(password: str) -> str:
    """Hash a plaintext password, or normalize an existing md5 value."""
    password = password.strip()
    if not password:
        raise ShGasCliError("password 不能为空")
    if re.fullmatch(r"[0-9a-fA-F]{32}", password):
        return password.lower()
    return hashlib.md5(password.encode()).hexdigest()


def decode_base64_image(value: str) -> bytes:
    """Decode a base64 captcha image."""
    if "," in value:
        value = value.split(",", 1)[1]
    try:
        return base64.b64decode(value)
    except binascii.Error as err:
        raise ShGasCliError("验证码图片不是有效 base64") from err


def normalize_captcha_code(value: str) -> str | None:
    """Normalize OCR text to the four-character captcha format."""
    normalized = "".join(ch for ch in value.upper() if ch.isalnum())
    if len(normalized) != 4:
        return None
    return normalized


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
