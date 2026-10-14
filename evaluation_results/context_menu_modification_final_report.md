# SafeMeal Context Menu Modification Final Report

## 1. Original Failure

The first turn correctly produced a 16-dish banquet with quotas `3/2/4/5/1/1`. In the same session, `重新推荐荤菜` was then treated as an ordinary recommendation: the canonical request had no inherited count, so rendering fell back to three recipes and category behavior could be inferred from prose rather than enforced by the business contract.

## 2. Confirmed Root Cause

The assistant response already persisted `menu_execution_plan` and `menu_task_progress`, but `ConversationHistoryService` reduced prior messages to role/content and did not expose message metadata to the next turn. Consequently, the next request could not read the previous meat quota or selected recipe IDs. In parallel, request understanding did not model reroll wording as `MODIFICATION + REPLACE`. The planner could sometimes guess facts from raw conversation text, but those guesses were not canonical and the response layer still lacked `requested_count=5`.

The original non-meat result was therefore caused by a dropped structured category contract, not by one bad recipe name. The fix passes `category=meat` through the canonical menu plan and existing search/category verification path; no recipe-specific exclusion was added.

## 3. Architecture Change

Before:

```text
assistant metadata contains menu plan/progress
→ history adapter keeps only role/content
→ next turn cannot resolve quota or previous selection
→ LLM may guess from prose
```

After:

```text
assistant metadata persists active_menu(plan + progress)
→ ConversationHistoryService loads latest structured active_menu
→ ContextBuilder attaches it to Conversation Context
→ PrepareContext resolves MODIFICATION/REFERENCE
→ existing planner receives category, count, and exclusions
→ response merges only the replaced category into active_menu
```

Only durable business state is carried forward. Candidate pools, tool results, iteration counters, and other turn-execution state remain turn-local.

## 4. Files Changed

- `safemeal/application/contracts/workflow/request_frame.py`: added menu-category target and replace operation contracts.
- `safemeal/application/service/chat/menu_planning.py`: generic modification parsing, clause binding, explicit counts, and structured ordinal reference resolution.
- `safemeal/application/service/chat/request_understanding.py`: emits modification semantics without naming a tool.
- `safemeal/application/service/chat/conversation_history_service.py`: loads the latest structured active menu from assistant metadata.
- `safemeal/application/workflow/context/builder.py`: places active menu in conversation context.
- `safemeal/application/workflow/nodes/prepare_context.py`: inherits quota/scenario and resolves previous recipe IDs and ordinal references.
- `safemeal/application/contracts/agent/menu_planning.py`: carries replacement exclusions in menu progress.
- `safemeal/application/agent/orchestration/nodes/initializer/node.py`: initializes replacement exclusions.
- `safemeal/application/agent/orchestration/nodes/planner/menu_planning.py`: forwards structural exclusions to existing recipe search.
- `safemeal/application/agent/orchestration/nodes/observer/menu_progress.py`: retains exclusions while observing progress.
- `safemeal/application/agent/gateway/service.py`: persists active menu and merges only the modified category after execution.
- `safemeal/application/service/dietary_safety/ingredient_terms.py`: expands generic chicken-meat exclusion to concrete chicken cuts.
- `tests/evaluation/test_menu_context_modification.py`: focused contract/component coverage.
- `tests/e2e/context_menu_modification_full_chain.py`: repeatable authenticated HTTP/SSE full-chain test.

## 5. Iteration History

Full append-only evidence is in `context_menu_modification_fix_log.md` and its JSON counterpart.

- Baseline: confirmed persisted metadata was not loaded and replacement semantics were absent.
- Iteration 1: added structured active-menu flow; found and fixed count-after-operation syntax.
- Iteration 2: core passed; real matrix exposed clause scope, category-local ordinal reference, and chicken taxonomy gaps.
- Iteration 3: fixed terse cross-clause category inheritance; all core, matrix, control, and regression tests passed.

Total modification rounds: 3. Failed/intermediate rounds: 2. Successful final round: 1. The fallback document was not consulted because the third round solved the remaining failure.

## 6. Final E2E Trace

- Session/conversation: `f6a454b0-aeed-495d-9c7d-6233f8fa1e69`
- Turn 1 message: `512`; coverage `cold=3, hot=2, vegetarian=4, meat=5, soup=1, staple=1`; total 16.
- Turn 2 message: `514` over SSE.
- Canonical relation/operation/target/count: `modification / replace / meat / 5`.
- Excluded old meat IDs: `[1, 21, 22, 37, 41]`.
- New meat IDs: `[17, 19, 29, 52, 60]`.
- Old/new intersection: empty.
- Returned category validation: five of five assigned to `meat`.
- Other active-menu categories: unchanged.
- SSE lifecycle: `accepted → progress → answer → done`.

## 7. Regression Results

- Component modification tests: 6 passed.
- `tests/refactor` + `tests/evaluation`: 239 passed.
- Ruff and `git diff --check`: passed.
- CM02–CM06: all passed.
- NEW_TASK `推荐四道鱼`: passed; count 4 and no banquet quota inheritance.
- REFERENCE `第二道荤菜怎么做？`: passed using structured display order.
- Required regressions passed: four fish, recipe detail, two-meat/two-vegetarian/one-soup, banquet 16, banquet then recipe detail, and three fish then second-item detail.

## 8. Remaining Risks

- `active_menu` lifecycle still relies on the current durable chat-message metadata store; Redis was intentionally not introduced.
- Modification parsing supports the tested category replacement family but not arbitrary nested natural-language edit programs.
- Category membership follows the project's existing taxonomy. For example, egg, seafood, or tofu-with-meat recipes may qualify as `meat`; this task did not redefine that taxonomy.
- The local request-understanding model was unavailable during E2E (`ConnectError`), so the existing deterministic fallback handled these requests. This did not bypass the actual workflow, planner, tools, safety, persistence, or SSE path.
