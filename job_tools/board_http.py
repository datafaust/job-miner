"""Small, shared retry policy for public job board requests."""

import os
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests


RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
MAX_RETRY_WAIT = 30
_last_request_at = 0.0


def _interval():
    try:
        return max(0.0, float(os.getenv("JOB_BOARD_REQUEST_INTERVAL_SECONDS", "0.25")))
    except ValueError:
        raise ValueError("JOB_BOARD_REQUEST_INTERVAL_SECONDS must be a number") from None


def _retry_after(response):
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def get_board(url, **kwargs):
    """Get a board feed, retrying brief throttling and temporary failures."""
    global _last_request_at
    for attempt in range(MAX_ATTEMPTS):
        remaining = _interval() - (time.monotonic() - _last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        _last_request_at = time.monotonic()
        try:
            response = requests.get(url, **kwargs)
        except (requests.Timeout, requests.ConnectionError):
            if attempt == MAX_ATTEMPTS - 1:
                raise
            time.sleep(random.uniform(0, 2 ** attempt))
            continue
        if response.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
            return response
        delay = _retry_after(response)
        if delay is None:
            delay = random.uniform(0, 2 ** attempt)
        if delay > MAX_RETRY_WAIT:
            return response
        time.sleep(delay)
