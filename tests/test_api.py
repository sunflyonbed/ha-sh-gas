"""Tests for the Shanghai Gas API helpers."""

from __future__ import annotations

from datetime import date

from custom_components.sh_gas.api import (
    _extract_ocr_code,
    _find_account,
    _is_captcha_error,
    _normalize_captcha_code,
    _parse_bill,
    _password_hash,
)


def test_find_account_matches_customer_id() -> None:
    """A login account is matched by customer id."""
    account = _find_account(
        [
            {
                "accountId": "46515278",
                "customerId": "46515278",
                "companyCode": "DZ",
                "customerName": "*",
                "customerAddress": "*",
                "dept": "长宁",
                "gasClass": "天然气",
            }
        ],
        "46515278",
    )

    assert account is not None
    assert account.customer_id == "46515278"
    assert account.company_code == "DZ"
    assert account.gas_class == "天然气"


def test_parse_bill() -> None:
    """A captured gas bill is normalized."""
    bill = _parse_bill(
        {
            "billYM": "2026-04",
            "money": "81.0",
            "overdueFine": "0.0",
            "consumption": 27.0,
            "yearConsumption": 27.0,
            "price": 3.0,
            "lastReading": "2549.0",
            "currentReading": "2576.0",
            "paymentStatus": "已付款",
            "billingDate": "2026-04-14 09:11:18",
            "readDate": "2026-04-14 00:00:00",
            "nextReadDate": "2026-06-15 00:00:00",
        }
    )

    assert bill.period == "2026-04"
    assert bill.period_date == date(2026, 4, 1)
    assert bill.amount == 81.0
    assert bill.consumption == 27.0
    assert bill.current_reading == 2576.0
    assert bill.next_read_date == date(2026, 6, 15)


def test_password_hash_accepts_plaintext_and_existing_md5() -> None:
    """Plain passwords are hashed and existing md5 values are preserved."""
    assert _password_hash("password") == "5f4dcc3b5aa765d61d8327deb882cf99"
    assert (
        _password_hash("5F4DCC3B5AA765D61D8327DEB882CF99")
        == "5f4dcc3b5aa765d61d8327deb882cf99"
    )


def test_normalize_captcha_code() -> None:
    """OCR output is normalized to the four-character captcha format."""
    assert _normalize_captcha_code(" g e1b ") == "GE1B"
    assert _normalize_captcha_code("GE1") is None


def test_extract_ocr_code() -> None:
    """OCR API responses are accepted with common result field names."""
    assert _extract_ocr_code({"code": "GE1B"}) == "GE1B"
    assert _extract_ocr_code({"data": {"result": " ab12 "}}) == "ab12"
    assert _extract_ocr_code({"code": 0, "data": "CD34"}) == "CD34"
    assert _extract_ocr_code({"ok": True}) is None


def test_is_captcha_error() -> None:
    """Captcha-related upstream auth errors are classified separately."""
    assert _is_captcha_error("验证码错误")
    assert _is_captcha_error("invalid imgAuthCode")
    assert not _is_captcha_error("密码错误")
