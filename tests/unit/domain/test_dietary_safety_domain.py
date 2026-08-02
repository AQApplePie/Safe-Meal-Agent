from safemeal.modules.dietary_safety.domain import (
    Evidence,
    EvidenceBundle,
    FailClosedPolicy,
    Ingredient,
    RecipeEligibilityPolicy,
    RecipeSafetyInput,
    SafetyStatus,
    ingredient_matches_forbidden_term,
)


def _input(
    *ingredients: str,
    complete: bool = True,
    available: bool = True,
    conflicts: tuple[str, ...] = (),
) -> RecipeSafetyInput:
    return RecipeSafetyInput(
        recipe_name="测试菜",
        ingredients=tuple(Ingredient(item) for item in ingredients),
        forbidden_terms=("花生",),
        evidence=EvidenceBundle(
            items=(Evidence("mysql", "recipe:1"),),
            ingredients_complete=complete,
            core_source_available=available,
            conflicting_sources=conflicts,
        ),
    )


def test_only_explicit_safe_decision_is_recommendable() -> None:
    policy = RecipeEligibilityPolicy()
    fail_closed = FailClosedPolicy()

    safe = policy.decide(_input("鸡肉", "黄瓜"))
    unsafe = policy.decide(_input("鸡肉", "花生油"))
    unknown = policy.decide(_input("鸡肉", complete=False))

    assert safe.status is SafetyStatus.SAFE
    assert unsafe.status is SafetyStatus.UNSAFE
    assert unsafe.matched_ingredients == ("花生油",)
    assert unknown.status is SafetyStatus.UNKNOWN
    assert fail_closed.allows_recommendation(safe)
    assert not fail_closed.allows_recommendation(unsafe)
    assert not fail_closed.allows_recommendation(unknown)


def test_missing_core_source_and_conflicting_evidence_fail_closed() -> None:
    policy = RecipeEligibilityPolicy()

    unavailable = policy.decide(_input("鸡肉", available=False))
    conflict = policy.decide(_input("鸡肉", conflicts=("mysql", "neo4j")))

    assert unavailable.status is SafetyStatus.UNKNOWN
    assert unavailable.risks[0].code == "core_source_unavailable"
    assert conflict.status is SafetyStatus.UNKNOWN
    assert conflict.risks[0].code == "evidence_conflict"


def test_broad_terms_do_not_create_substring_false_positives() -> None:
    assert ingredient_matches_forbidden_term("蟹肉", "蟹")
    assert not ingredient_matches_forbidden_term("蟹味菇", "蟹")
    assert not ingredient_matches_forbidden_term("鱼香肉丝调料", "鱼")
