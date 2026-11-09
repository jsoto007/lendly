from __future__ import annotations

import uuid
from datetime import date

from flask import request

from ..auth import api_error


class BadInput(Exception):
    """A validation error. `message` is an English template; it's translated when rendered."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message)
        self.message = message
        self.kwargs = kwargs


def body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadInput("JSON body required.")
    return data


def req_str(data: dict, key: str, max_len: int = 255, required: bool = True) -> str | None:
    value = data.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise BadInput("{key} is required.", key=key)
        return None
    if not isinstance(value, str):
        raise BadInput("{key} must be text.", key=key)
    return value.strip()[:max_len]


MAX_CENTS = 100_000_000_000  # $1,000,000,000.00 — far above any informal loan, far below int64


def req_int(data: dict, key: str, required: bool = True, default: int = 0, minimum: int | None = None,
            maximum: int | None = None) -> int:
    value = data.get(key)
    if value is None:
        if required:
            raise BadInput("{key} is required.", key=key)
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise BadInput("{key} must be a whole number.", key=key)
    if minimum is not None and value < minimum:
        raise BadInput("{key} must be at least {minimum}.", key=key, minimum=minimum)
    if maximum is not None and value > maximum:
        raise BadInput("{key} is too large.", key=key)
    return value


def query_int(name: str, default: int, lo: int, hi: int) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return max(lo, min(int(raw), hi))
    except ValueError:
        raise BadInput("{key} must be a whole number.", key=name)


def local_today() -> date:
    """The caller's calendar date. The app sends X-Local-Date (its device date) so a lender in
    New York at 9pm isn't treated as 'tomorrow' by a UTC server. Falls back to server date."""
    raw = request.headers.get("X-Local-Date", "")
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        return date.today()
    # Don't trust wildly wrong clocks: clamp to ±2 days around server time.
    server = date.today()
    if abs((d - server).days) > 2:
        return server
    return d


def req_bool(data: dict, key: str, default: bool = False) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise BadInput("{key} must be true or false.", key=key)
    return value


def req_date(data: dict, key: str, required: bool = True, default: date | None = None) -> date | None:
    value = data.get(key)
    if value is None:
        if required:
            raise BadInput("{key} is required.", key=key)
        return default
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise BadInput("{key} must be a date like 2026-10-14.", key=key)


def req_choice(data: dict, key: str, choices: tuple, required: bool = True, default: str | None = None) -> str | None:
    value = data.get(key, default)
    if value is None and not required:
        return None
    if value not in choices:
        raise BadInput("{key} must be one of: {choices}.", key=key, choices=", ".join(choices))
    return value


def parse_uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        raise BadInput("Invalid id.")


def handle_bad_input(bp):
    @bp.errorhandler(BadInput)
    def _bad(e: BadInput):
        return api_error(422, "invalid", e.message, **e.kwargs)
