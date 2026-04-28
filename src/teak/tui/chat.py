from __future__ import annotations

from textual.app import App


class ChatApp(App):
    """Inline chat surface for QuickMode and free-form Q&A."""

    def on_mount(self) -> None:
        raise NotImplementedError
