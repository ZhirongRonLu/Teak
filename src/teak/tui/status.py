from __future__ import annotations

from textual.app import App

from teak.config import TeakConfig


class StatusApp(App):
    """Live token dashboard rendered via `teak status`.

    Shows: spend so far, budget remaining, estimated cost of the next action,
    brain file health (last update, missing files), and indexer staleness.
    """

    def __init__(self, config: TeakConfig) -> None:
        super().__init__()
        self.config = config

    def on_mount(self) -> None:
        raise NotImplementedError
