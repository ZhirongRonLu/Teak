from __future__ import annotations

from typing import Any, Optional


def build_cached_messages(
    *,
    cached_prefix: str,
    instructions: str = "",
    user_messages: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Construct an Anthropic-cacheable message list.

    The system prompt is split into two text blocks:

      1. `cached_prefix` — the durable Project Brain content. Marked with
         Anthropic `cache_control: ephemeral` so the first call writes it to
         the cache (full price) and every subsequent call within the 5-minute
         TTL reads from cache (~10% input price).
      2. `instructions` — the per-call agent role / output-format rules. Not
         cached; cheap to ship and changes per node.

    Provider neutrality: LiteLLM forwards `cache_control` to Anthropic and
    drops it for OpenAI / Voyage / etc., so the same builder works everywhere.
    """
    if not cached_prefix and not instructions:
        raise ValueError("cached_prefix or instructions must be non-empty")

    system_blocks: list[dict[str, Any]] = []
    if cached_prefix.strip():
        system_blocks.append(
            {
                "type": "text",
                "text": cached_prefix,
                "cache_control": {"type": "ephemeral"},
            }
        )
    if instructions.strip():
        system_blocks.append({"type": "text", "text": instructions})

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_blocks}]
    if user_messages:
        messages.extend(user_messages)
    return messages
