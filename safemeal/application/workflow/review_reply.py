"""实现聊天工作流中的对应职责。"""

from safemeal.application.contracts.dietary_safety.requirements import (
    DietaryReviewResult,
)


def render_review_reply(review: DietaryReviewResult) -> str:
    return render_conversational_review_reply(review)


def render_conversational_review_reply(
    review: DietaryReviewResult, *, max_recommendations: int | None = None
) -> str:

    limit = max_recommendations or 3
    passed = [item for item in review.recipes if item.decision == "passed"][:limit]
    if not passed:
        if any(item.decision == "unknown" for item in review.recipes):
            return (
                "目前候选食谱的食材信息不够完整，无法确认它们是否同时满足你的要求。"
                "你可以换一个目标食材，或者让我生成一份符合条件的新食谱。"
            )
        if review.recipes:
            return (
                "暂时没有找到同时满足你本轮要求的食谱。"
                "你可以调整其中一个条件，或者让我继续扩大查找范围。"
            )
        return (
            "暂时没有找到可核验的食谱。请告诉我想吃的主要食材、需要避开的食材，"
            "或者希望的烹饪方式。"
        )

    if len(passed) == 1:
        item = passed[0]
        lines = [f"推荐你试试「{item.name}」。"]
        if item.evidence.ingredients:
            lines.append(f"主要食材：{'、'.join(item.evidence.ingredients)}。")
        confirmations = _human_confirmations(item.preferences)
        if confirmations:
            lines.append("这道菜" + "，并且".join(confirmations) + "。")
        return "\n\n".join(lines)

    lines = [f"可以优先考虑下面这 {len(passed)} 道菜："]
    for item in passed:
        ingredients = "、".join(item.evidence.ingredients)
        lines.append(
            f"- 「{item.name}」：主要食材有{ingredients}。"
            if ingredients
            else f"- 「{item.name}」"
        )
    lines.append("这些结果已经按你本轮提出的必要条件完成筛选。")
    return "\n".join(lines)


def _human_confirmations(assessments) -> list[str]:

    confirmations: list[str] = []
    for assessment in assessments:
        preference = assessment.preference
        if not preference.required or assessment.status != "satisfied":
            continue
        if preference.kind == "include_ingredient":
            confirmations.append(f"包含你指定的{preference.value}")
        elif preference.kind == "avoid_ingredient":
            confirmations.append(f"食材中未发现你要求避开的{preference.value}")
        elif preference.kind == "max_minutes":
            confirmations.append(f"可在{preference.value}分钟内完成")
        elif preference.kind == "dietary_type":
            confirmations.append("符合你指定的饮食类型")
        elif preference.kind == "equipment":
            confirmations.append(f"可以使用{preference.value}制作")
    return confirmations
