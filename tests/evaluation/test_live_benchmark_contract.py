"""Offline checks for the live evaluator; no model calls during normal pytest."""

from scripts.evaluate_agent_live import CATALOG, grade, load_cases, published_names


def test_live_corpus_has_stable_ids_and_separate_oracles():
    cases = load_cases()
    assert len(cases) == len({c["id"] for c in cases}) == 12
    assert all(c["turns"] and c["expected"] for c in cases)
    assert {"injection", "tool_failure", "allergy", "reference", "replacement"} <= {
        c["group"] for c in cases
    }


def test_unknown_names_cannot_pass_category_or_safety_checks():
    case = dict(expected=dict(count=2, category="fish", avoid="花生"))
    assert "unknown_published_recipe" in grade(
        case, [dict(answer="推荐", recipes=["假鱼1", "假鱼2"])]
    )
    assert "allergy_violation" in grade(
        dict(expected=dict(avoid="花生")),
        [dict(answer="推荐", recipes=["花生凉拌黄瓜"])],
    )


def test_missing_fields_and_operational_failure_cannot_pass():
    assert grade(
        dict(expected=dict(contains=["蒸十分钟"])), [dict(answer="很好吃", recipes=[])]
    ) == ["answer_fields"]
    assert "execution_error" in grade(
        dict(expected={}), [dict(http_status=503, message="不可用")]
    )


def test_replacement_must_preserve_four_and_change_one_vegetarian():
    before = ["清蒸鲈鱼", "红烧牛肉", "蒜蓉西兰花", "香菇青菜", "冬瓜汤"]
    after = ["清蒸鲈鱼", "红烧牛肉", "凉拌黄瓜", "香菇青菜", "冬瓜汤"]
    case = dict(expected=dict(count=5, replace=True))
    assert grade(case, [dict(recipes=before), dict(recipes=after)]) == []
    assert "replacement_scope" in grade(
        case, [dict(recipes=before), dict(recipes=before)]
    )


def test_overlapping_catalog_names_are_not_double_counted():
    assert published_names(dict(message="推荐「花生凉拌黄瓜」")) == ["花生凉拌黄瓜"]
    assert len({r["name"] for r in CATALOG}) == len(CATALOG)


def test_expected_database_503_is_a_degradation_then_recovery():
    case = dict(expected=dict(recover=True, contains=["鲈鱼"]))
    first = dict(http_status=503, detail=dict(error_code="database_unavailable"))
    assert grade(case, [first, dict(http_status=200, message="鲈鱼")]) == []
    assert "execution_error" in grade(
        case, [first, dict(http_status=503, message="不可用")]
    )


def test_plant_soups_can_fill_vegetarian_slots_but_not_double_count():
    from scripts.evaluate_agent_live import satisfies_quotas

    selected = [CATALOG[0], CATALOG[1], CATALOG[7], CATALOG[5], CATALOG[8]]
    assert satisfies_quotas(selected, dict(meat=2, vegetarian=2, soup=1))
    assert not satisfies_quotas(selected, dict(meat=2, vegetarian=2, soup=2))


def test_two_overlapping_titles_are_distinct_published_recipes():
    text = "- 凉拌黄瓜（主要食材：黄瓜）\n- 花生凉拌黄瓜（主要食材：花生、黄瓜）"
    assert published_names(dict(message=text)) == ["凉拌黄瓜", "花生凉拌黄瓜"]


def test_ingredient_bullets_are_not_unknown_recipe_recommendations():
    assert (
        grade(
            dict(expected=dict(contains=["鲈鱼", "盐"])),
            [dict(message="清蒸鲈鱼的材料：\n- 鲈鱼：100g\n- 盐：1g")],
        )
        == []
    )


def test_isolated_empty_catalog_is_valid_and_reports_not_found(tmp_path):
    import os
    from unittest.mock import patch
    from safemeal.infrastructure.retrieval.local_recipe_catalog import (
        LocalRecipeDocumentCatalog,
    )
    from scripts.evaluate_agent_live import isolate

    with patch.dict(os.environ):
        isolate(str(tmp_path))
        catalog = LocalRecipeDocumentCatalog(os.environ["NEO4J_RECIPE_JSON_PATH"])
        assert catalog.lookup("不存在的银河炖龙").status == "NOT_FOUND"
        assert os.environ["DATABASE_URL"] == f"sqlite:///{tmp_path}/app.sqlite"
