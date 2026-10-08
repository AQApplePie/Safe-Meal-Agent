"""Regression suite for bounded short-term recipe reference resolution."""

from safemeal.agent.understanding.request_understanding import (
    RequestUnderstandingService,
)


def test_single_recipe_pronoun_resolves_to_recent_recommendation():
    history = [
        {"role": "user", "content": "推荐一道鱼"},
        {"role": "assistant", "content": "推荐你试试「柠檬蒸三文鱼」。"},
    ]

    frame = RequestUnderstandingService().understand("这个怎么做？", history)

    assert frame.primary_task == "recipe_detail"
    assert frame.target.recipe_name == "柠檬蒸三文鱼"
    assert frame.requested_fields == ("steps",)


def test_ordinal_resolves_against_ordered_recent_recommendations():
    history = [
        {
            "role": "assistant",
            "content": (
                "可以优先考虑下面这 3 道菜：\n"
                "- 「清蒸鲈鱼」\n- 「柠檬蒸三文鱼」\n- 「豆豉蒸鲈鱼」"
            ),
        }
    ]

    frame = RequestUnderstandingService().understand("第二个怎么做？", history)

    assert frame.primary_task == "recipe_detail"
    assert frame.target.recipe_name == "柠檬蒸三文鱼"
    assert frame.requested_fields == ("steps",)


def test_elliptical_steps_resolve_when_recent_target_is_unique():
    history = [{"role": "assistant", "content": "柠檬蒸三文鱼"}]

    frame = RequestUnderstandingService().understand("具体步骤呢？", history)

    assert frame.primary_task == "recipe_detail"
    assert frame.target.recipe_name == "柠檬蒸三文鱼"
    assert frame.requested_fields == ("steps",)


def test_ambiguous_pronoun_requests_clarification_instead_of_guessing():
    history = [
        {
            "role": "assistant",
            "content": "- 「清蒸鲈鱼」\n- 「豆豉蒸鲈鱼」",
        }
    ]

    frame = RequestUnderstandingService().understand("那个怎么做？", history)

    assert frame.primary_task == "clarify"
    assert frame.target.recipe_name in {None, "那个"}
    assert frame.clarification_question
    assert "第几个" in frame.clarification_question
