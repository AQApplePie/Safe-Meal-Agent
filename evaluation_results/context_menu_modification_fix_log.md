# SafeMeal Context Menu Modification Fix Log

本文件只追加记录，不覆盖历史迭代。

==================================================
BASELINE DIAGNOSIS
==================================================

Timestamp: 2026-10-04 Asia/Shanghai

Scope: 仅诊断“完整菜单 → 修改某一菜单分类”的结构化上下文继承问题。

Status: IN_PROGRESS

Observed baseline:
- session_id: `39b55837-5d94-4c1c-a826-ee43f62b69f3`
- turn_1_id: `414`
- turn_2_id: `416`
- Turn 1: 16/16 complete; metadata contains `menu_execution_plan` and `menu_task_progress`.
- Turn 2 frame: `context_relation=new_task`, ordinary recommendation, count missing.
- Turn 2 tool: `category=meat`, old five meat names excluded, but this came from model inference over raw history.
- Turn 2 response: defaulted to 3 recipes.

Confirmed root cause:
`ConversationHistoryService` discards assistant `message_metadata`, so persisted menu state never enters `ConversationContext`. Request understanding also does not classify “重新” as modification. The responder therefore has no canonical inherited count.

Diagnosis answers:
1. “重新” is lost in rule relation classification.
2. active_menu is persisted in assistant message metadata but cannot be read by context builder.
3. meat quota=5 is absent from canonical Turn 2 state.
4. old five meats are guessed by the planner model from raw text, not structurally resolved.
5. category=meat reaches `search_recipes` in this run.
6. missing canonical requested_count makes response rendering fall back to 3.
7. category taxonomy/service is the authority; recipe-name filtering would be invalid.

Next hypothesis:
Load the latest persisted menu metadata as a bounded `active_menu`, enrich MODIFICATION deterministically, and pass structural exclusions into the existing menu search planner.

==================================================
ITERATION 1
==================================================

Timestamp: 2026-10-04 Asia/Shanghai

Git HEAD before modification: `d982a3402e1cc153238a07806d201ea34ac543fe`

Observed failure:
Focused unit tests: 2 passed, 1 failed. `荤菜改成三道` retained category=meat but count was None.

Root cause hypothesis:
The quota parser only supported number-before-category order; modification language commonly places the new count after `改成/换成`.

Files changed:
- request/menu context contracts and adapters
- history/context loading
- existing menu planner exclusion adapter
- `menu_planning.py` count-order rule

Tests executed:
- existing focused regression set: 68 passed
- new modification tests before count fix: 2 passed, 1 failed

Regression observed: NO

Next hypothesis:
After supporting change-verb count order, rebuild and run exact two-turn HTTP E2E.

==================================================
ITERATION 2
==================================================

Timestamp: 2026-10-04 Asia/Shanghai

Observed real-matrix results:
- Core `重新推荐荤菜`: PASS; inherited meat count=5, excluded all previous five, returned five non-overlapping meat-category recipes.
- CM02 `重新推荐素菜`: PASS.
- CM03 `汤换一个`: PASS.
- CM04 `荤菜改成三道`: PASS.
- CM05 `荤菜不要鸡肉，重新推荐`: FAIL; a chicken-leg recipe remained.
- CM06 `素菜保留，荤菜重新推荐`: FAIL; the first mentioned category was selected instead of the replacement clause target.
- NEW_TASK `推荐四道鱼`: PASS and remained `new_task`.
- REFERENCE `第二道荤菜怎么做？`: FAIL; ordinal text was treated as a literal recipe name.

Root-cause hypothesis:
1. Modification target extraction scans the entire sentence and ignores clause scope.
2. Active-menu ordinal references are not resolved from persisted structured selections.
3. Dietary alias taxonomy has no `鸡肉` expansion to concrete cuts such as `鸡腿肉`.

Files changed:
- `safemeal/application/service/chat/menu_planning.py`
- `safemeal/application/workflow/nodes/prepare_context.py`
- `safemeal/application/service/dietary_safety/ingredient_terms.py`
- `tests/evaluation/test_menu_context_modification.py`

Verification after change:
- focused unit tests: 5 passed
- Ruff: passed
- one discarded system-Python invocation failed during collection because that environment lacks `langgraph`; project `agent_env` was then used successfully.

Next hypothesis:
Rebuild the API and rerun the real HTTP/SSE scenario matrix to validate structured-state behavior end to end.

==================================================
ITERATION 3
==================================================

Timestamp: 2026-10-04 Asia/Shanghai

Observed failure:
After Iteration 2, CM05 classified `荤菜不要鸡肉，重新推荐` as a modification relation but did not bind a replacement operation/category because the replacement clause omitted the category.

Root cause hypothesis and evidence:
The category was in the immediately preceding clause while `重新推荐` was in a terse second clause. The dietary exclusion itself was already extracted correctly. This is a request-understanding clause-binding gap, not a planner or safety failure.

Files changed:
- `safemeal/application/service/chat/menu_planning.py`
- `tests/evaluation/test_menu_context_modification.py`
- `tests/e2e/context_menu_modification_full_chain.py`

Exact behavior changed:
When a replacement clause has no category, it inherits the nearest category mention from the request. A category explicitly present in the replacement clause still wins.

Tests executed and results:
- component tests: 6 passed
- focused refactor/evaluation suite: 239 passed
- Ruff over application and new tests: PASS
- real authenticated HTTP/SSE E2E: PASS
- CM02-CM06: all PASS
- NEW_TASK control: PASS
- REFERENCE control: PASS
- six required regression scenarios: all PASS

Actual core E2E output:
- session_id / conversation_id: `f6a454b0-aeed-495d-9c7d-6233f8fa1e69`
- Turn 1 assistant message_id: `512`
- Turn 2 assistant message_id: `514`
- Turn 1 coverage: 3 cold, 2 hot, 4 vegetarian, 5 meat, 1 soup, 1 staple; total 16
- Turn 2 requested/returned: 5/5
- old meat IDs: `[1, 21, 22, 37, 41]`
- new meat IDs: `[17, 19, 29, 52, 60]`
- overlap: empty
- all assigned category meat: YES
- untouched categories preserved: YES
- SSE events included accepted, progress, answer, done

Regression observed: NO

Git diff summary:
12 existing application files changed; two test files and three evaluation artifacts added. No workflow node, graph node, tool, or database schema was added.

Result: PASS / COMPLETE
