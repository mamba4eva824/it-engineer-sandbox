"""Shared HTTP helper: retry 429/5xx and transport failures only. Never 401/403/404."""
from __future__ import annotations

import os
import time
from typing import Any

import requests

MAX_ATTEMPTS = int(os.environ.get("LICENSE_HTTP_MAX_ATTEMPTS", "3"))
BACKOFF_SECONDS = float(os.environ.get("LICENSE_HTTP_BACKOFF_SECONDS", "0.25"))
ERROR_TRUNCATE = 500


def truncate_error(message: str | None) -> str | None:
    if not message:
        return None
    text = str(message).replace("\n", " ").strip()
    return text[:ERROR_TRUNCATE]


def request_with_retry(
    method: str,
    url: str,
    *,
    timeout: int = 15,
    max_attempts: int | None = None,
    **kwargs: Any,
) -> requests.Response:
    attempts = max_attempts if max_attempts is not None else MAX_ATTEMPTS
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            if attempt >= attempts:
                raise
            time.sleep(BACKOFF_SECONDS * attempt)
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt >= attempts:
                return resp
            time.sleep(BACKOFF_SECONDS * attempt)
            continue
        return resp
    if last_exc:
        raise last_exc
    raise RuntimeError("request_with_retry exhausted without a response")


def finding(
    *,
    app: str,
    status: str,
    seat_type: str | None = None,
    action_hint: str | None = None,
    error_class: str | None = None,
    http_status: int | None = None,
    retryable: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "app": app,
        "status": status,
        "seat_type": seat_type,
        "action_hint": action_hint,
        "error_class": error_class,
        "http_status": http_status,
        "retryable": retryable,
        "error": truncate_error(error),
    }
