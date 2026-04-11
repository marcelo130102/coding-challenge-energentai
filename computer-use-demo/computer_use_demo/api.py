"""Anthropic SDK client construction and thin wrappers for Messages API calls."""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Any

from anthropic import Anthropic, AnthropicBedrock, AnthropicVertex
from anthropic.types.beta import (
    BetaMessageParam,
    BetaTextBlockParam,
    BetaToolUnionParam,
)


class APIProvider(StrEnum):
    ANTHROPIC = "anthropic"
    BEDROCK = "bedrock"
    VERTEX = "vertex"


def build_anthropic_client(api_key: str) -> Anthropic:
    """Prefer env vars injected by Docker orchestration, then the passed api_key."""
    key = os.getenv("ANTHROPIC_API_KEY") or api_key
    base = os.getenv("ANTHROPIC_BASE_URL", "").strip()
    if base:
        return Anthropic(
            api_key=key,
            max_retries=4,
            base_url=base.rstrip("/"),
        )
    return Anthropic(api_key=key, max_retries=4)


def messages_client_for_provider(
    provider: APIProvider,
    api_key: str,
) -> Anthropic | AnthropicBedrock | AnthropicVertex:
    """Instantiate the SDK client for the given API surface (Anthropic, Bedrock, or Vertex)."""
    if provider == APIProvider.ANTHROPIC:
        return build_anthropic_client(api_key)
    if provider == APIProvider.VERTEX:
        return AnthropicVertex()
    if provider == APIProvider.BEDROCK:
        return AnthropicBedrock()
    raise RuntimeError(f"Unsupported API provider: {provider!r}")


def create_beta_messages_with_raw_response(
    client: Anthropic | AnthropicBedrock | AnthropicVertex,
    *,
    max_tokens: int,
    messages: list[BetaMessageParam],
    model: str,
    system: list[BetaTextBlockParam],
    tools: list[BetaToolUnionParam],
    betas: list[str],
    extra_body: dict[str, Any],
) -> Any:
    """Call ``beta.messages.with_raw_response.create`` (used for HTTP debug callbacks)."""
    return client.beta.messages.with_raw_response.create(
        max_tokens=max_tokens,
        messages=messages,
        model=model,
        system=system,
        tools=tools,
        betas=betas,
        extra_body=extra_body,
    )
