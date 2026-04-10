from __future__ import annotations

from .schemas import SessionCreate

# PackyAPI (e.g. Chinese candidates) — Anthropic-compatible base URL.
PACKYAPI_DEFAULT_BASE_URL = "https://www.packyapi.com"


def resolve_anthropic_base_url(body: SessionCreate) -> tuple[str | None, str]:
    """
    Returns (stored_base_url, endpoint_label).

    stored_base_url None means use the Anthropic SDK default (global API).
    endpoint_label is one of: global, packyapi, custom.
    """
    if body.base_url is not None:
        url = str(body.base_url).rstrip("/")
        return url, "custom"
    if body.api_endpoint == "packyapi":
        return PACKYAPI_DEFAULT_BASE_URL, "packyapi"
    return None, "global"
