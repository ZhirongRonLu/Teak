from __future__ import annotations

from textual.app import App

from teak.flow.state import PlanStep


class ApprovalApp(App):
    """Interactive plan-approval TUI.

    For each `PlanStep`, the user can approve, edit, or reject. Returns the
    edited list of steps once the user submits. Used as the human-in-the-loop
    surface for `flow.nodes.human_approval`.
    """

    def __init__(self, plan: list[PlanStep]) -> None:
        super().__init__()
        self.plan = plan

    def on_mount(self) -> None:
        raise NotImplementedError
