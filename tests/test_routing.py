from teak.llm.routing import TaskKind, choose_model


def test_planner_routed_to_cheap_model() -> None:
    assert choose_model(TaskKind.PLAN, default="big", planner="cheap") == "cheap"
    assert choose_model(TaskKind.SUMMARIZE, default="big", planner="cheap") == "cheap"


def test_codegen_routed_to_default() -> None:
    assert choose_model(TaskKind.GENERATE_CODE, default="big", planner="cheap") == "big"
