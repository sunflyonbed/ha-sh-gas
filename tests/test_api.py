"""Tests for the Shanghai Gas API helpers."""

from __future__ import annotations

from datetime import date

from custom_components.sh_gas.api import _find_account, _parse_bill


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
