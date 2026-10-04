from safemeal.application.contracts.dietary_safety.control_plane import (
    ConstraintDecision,
    ResolvedConstraints,
    ToolEvidence,
)
from safemeal.application.contracts.workflow.request_frame import (
    RawRequestFrame,
    RequestFrame,
)
from safemeal.application.contracts.workflow.semantic import ConstraintStatement
from safemeal.application.contracts.agent.context import AgentContext
from safemeal.application.service.chat.request_understanding import (
    RequestUnderstandingService,
)
from safemeal.application.service.dietary_safety.dietary_safety_service import (
    DietarySafetyService,
)
from safemeal.application.service.dietary_safety.constraint_resolver import (
    ConstraintResolver,
)
from safemeal.application.service.dietary_safety.constraint_evaluator import (
    ConstraintEvaluator,
)


def test_raw_and_canonical_frames_are_explicitly_distinguishable():
    assert RawRequestFrame().canonical is False
    assert RequestFrame().canonical is True


def test_resolved_constraints_group_statements_by_authority():
    allergy = ConstraintStatement(
        type="allergy",
        value="花生",
        owner="spouse",
        strength="hard_safety",
        source="current_input",
        scope="current_meal",
    )
    resolved = ResolvedConstraints(hard_safety=(allergy,))
    assert resolved.active == (allergy,)


def test_tool_evidence_and_decision_do_not_contain_raw_language():
    constraint = ConstraintStatement(
        type="taste",
        value="non_spicy",
        strength="strong_requirement",
        scope="current_meal",
    )
    evidence = ToolEvidence(
        recipe_name="清蒸鲈鱼",
        ingredients=("鲈鱼", "姜"),
        ingredients_complete=True,
        source="recipe:1",
        source_complete=True,
    )
    decision = ConstraintDecision(
        status="satisfied",
        constraint=constraint,
        recipe_name=evidence.recipe_name,
        reason="完整食材未命中辣味配料",
        evidence=evidence,
    )
    assert decision.status == "satisfied"


def test_rule_output_is_canonical_after_shared_normalizer():
    frame = RequestUnderstandingService().understand("我不喜欢姜，推荐三道菜")
    assert frame.canonical is True
    assert not any(
        item.kind == "include_ingredient" and item.value == "姜"
        for item in frame.turn_preferences
    )


def test_raw_history_cannot_reactivate_a_previous_constraint():
    frame = RequestUnderstandingService().understand(
        "我现在要办农村宴席，要求三道凉菜、两道热菜"
    ).model_copy(update={"understanding_status": "fallback"})
    requirements = DietarySafetyService().resolve_constraints(
        "我现在要办农村宴席，要求三道凉菜、两道热菜",
        [{"role": "user", "content": "我媳妇不吃辣"}],
        AgentContext(request_frame=frame),
    )
    assert requirements.restrictions.active is False
    assert all(item.source != "history" for item in requirements.preferences)


def test_context_relation_separates_new_task_reference_and_continuation():
    service = RequestUnderstandingService()
    assert service.understand("推荐三道菜").context_relation == "new_task"
    assert service.understand("再来三道").context_relation == "continuation"
    assert service.understand("这个怎么做").context_relation == "reference"


def test_participant_ownership_is_preserved_in_canonical_statements():
    frame = RequestUnderstandingService().understand(
        "老婆不吃辣，儿子不喜欢姜，我自己想吃鱼，给四个人安排午饭"
    )
    by_value = {item.value: item for item in frame.statements}
    assert by_value["non_spicy"].owner == "spouse"
    assert by_value["姜"].owner == "child"
    assert by_value["fish"].strength == "menu_goal"


def test_new_task_does_not_inherit_but_continuation_uses_explicit_carryover():
    resolver = ConstraintResolver()
    first = RequestUnderstandingService().understand("不要辣，推荐三道菜")
    previous = resolver.resolve(first, [])
    new_task = RequestUnderstandingService().understand("水煮鱼怎么做")
    continued = RequestUnderstandingService().understand("再来三道")
    assert not resolver.resolve(new_task, [], previous=previous).strong_requirements
    carried = resolver.resolve(continued, [], previous=previous)
    assert carried.strong_requirements[0].source == "explicit_carryover"


def test_non_spicy_uses_complete_ingredient_evidence_without_taste_field():
    constraint = ConstraintStatement(
        type="taste",
        value="non_spicy",
        strength="strong_requirement",
        scope="current_meal",
    )
    safe = ToolEvidence(
        recipe_name="清蒸鲈鱼",
        ingredients=("鲈鱼", "姜"),
        ingredients_complete=True,
        source_complete=True,
    )
    spicy = safe.model_copy(
        update={"recipe_name": "香辣鲈鱼", "ingredients": ("鲈鱼", "小米椒")}
    )
    evaluator = ConstraintEvaluator()
    assert evaluator.evaluate(constraint, safe).status == "satisfied"
    assert evaluator.evaluate(constraint, spicy).status == "violated"
