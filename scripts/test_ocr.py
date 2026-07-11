#!/usr/bin/env python3
"""Test the OCR API with a Shanghai Gas captcha only."""

from __future__ import annotations

import argparse
import json

from query_sh_gas import (
    ShGasCliError,
    default_ocr_api_url,
    extract_ocr_code,
    get_captcha,
    normalize_captcha_code,
    request_ocr_raw_json,
)


def main() -> int:
    """Fetch or read one captcha and send it to the OCR API."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ocr-api-url",
        default=default_ocr_api_url(),
        help="OCR endpoint URL. Default: %(default)s",
    )
    parser.add_argument(
        "--image-base64",
        help="Use this base64Image string instead of fetching a new captcha.",
    )
    args = parser.parse_args()

    try:
        if args.image_base64:
            imgid = None
            base64_image = args.image_base64
        else:
            captcha = get_captcha()
            imgid = captcha["imgid"]
            base64_image = captcha["base64_image"]

        response = request_ocr_raw_json(args.ocr_api_url, base64_image)
        raw_code = extract_ocr_code(response)
        normalized_code = normalize_captcha_code(raw_code) if raw_code else None
    except ShGasCliError as err:
        print(
            json.dumps(
                {"ok": False, "error": str(err)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "ok": normalized_code is not None,
                "ocr_api_url": args.ocr_api_url,
                "imgid": imgid,
                "raw_code": raw_code,
                "normalized_code": normalized_code,
                "ocr_response": response,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if normalized_code is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
