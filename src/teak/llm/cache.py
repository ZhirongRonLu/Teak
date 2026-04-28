from __future__ import annotations

from typing import Any


def build_cached_messages(
    system_prompt: str,
    brain_content: str,
    user_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Construct a message list with Anthropic cache_control on the brain prefix.

    The brain content is the cached prefix — full price on first call, ~10% on
    subsequent calls within the 5-minute TTL. User messages live after the
    cache breakpoint.
    """
    raise NotImplementedError(system_prompt, brain_content, user_messages)
