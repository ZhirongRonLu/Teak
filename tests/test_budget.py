import pytest

from teak.llm.budget import BudgetExceeded, BudgetTracker


def test_charge_within_budget() -> None:
    t = BudgetTracker(budget_usd=1.0)
    t.charge(0.3)
    t.charge(0.4)
    assert t.spent_usd == pytest.approx(0.7)
    assert t.remaining() == pytest.approx(0.3)


def test_charge_blocks_overrun() -> None:
    t = BudgetTracker(budget_usd=1.0, spent_usd=0.9)
    assert t.would_exceed(0.2)
    with pytest.raises(BudgetExceeded):
        t.charge(0.2)
    assert t.spent_usd == pytest.approx(0.9)
