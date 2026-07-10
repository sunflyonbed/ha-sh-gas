"""Constants for the Shanghai Gas integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "sh_gas"

PLATFORMS = ["sensor"]

BASE_URL = "https://mpshgas.huaqi-it.com.cn"
ORIGIN = "MiniPro"
DEFAULT_COMPANY_CODE = "DZ"

DEFAULT_SCAN_INTERVAL = timedelta(hours=6)

CONF_TOKEN = "token"
CONF_CUSTOMER_ID = "customer_id"
CONF_COMPANY_CODE = "company_code"

DATA_COORDINATOR = "coordinator"
DATA_CLIENT = "client"
