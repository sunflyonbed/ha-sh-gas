"""Constants for the Shanghai Gas integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "sh_gas"

PLATFORMS = ["sensor"]

BASE_URL = "https://mpshgas.huaqi-it.com.cn"
WEB_API_BASE_URL = "https://web-api.shgas.com.cn"
ORIGIN = "MiniPro"
PC_ORIGIN = "PC"
DEFAULT_COMPANY_CODE = "DZ"

DEFAULT_SCAN_INTERVAL = timedelta(days=1)

CONF_CUSTOMER_ID = "customer_id"
CONF_COMPANY_CODE = "company_code"
CONF_MOBILE = "mobile"
CONF_PASSWORD = "password"
CONF_PASSWORD_HASH = "password_hash"
CONF_OCR_API_URL = "ocr_api_url"

DATA_COORDINATOR = "coordinator"
DATA_CLIENT = "client"
