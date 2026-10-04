# SafeMeal Agent Failure Analysis Report

测试日期：2026-10-03（Asia/Shanghai）  
测试方式：本机 Docker 服务、公开 HTTP/SSE API、真实 Qwen3-1.7B 请求理解链路  
原始记录：[exploratory_failure_raw.json](./exploratory_failure_raw.json)、[exploratory_stream_raw.json](./exploratory_stream_raw.json)

## 1. Executive Summary

本轮按 Basic → Detail → Menu → Multi-turn → Preference/Safety → Multi-person → Recovery → State → Tool/Loop → Natural Language 顺序执行了附件定义的 56 个逻辑 Case，并补充 2 个 SSE 对照。

最严重问题不是复杂菜单 Loop，而是 `understand_request` 的空菜单配额契约：只要输入包含“安排午饭/晚饭”但没有明确荤素汤数量，系统尝试构造空 `category_quotas`，在进入 Planner 前抛出 Pydantic ValidationError。B02、I01–I06、N04 共 8 个场景稳定 HTTP 500；SSE 表现为 `accepted → progress(understand_request) → error(stream_failed) → done(error)`。

正向结论：显式数量、四道鱼、标准配额菜单、16 道宴席、明确食谱步骤，以及大部分短期指代已经稳定。失败后同一 session 可立即恢复，宴席与四道鱼都没有复现 checkpoint 污染。

## 2. Test Environment and Observability

- API：`http://127.0.0.1:8000/api/v1`
- API 容器：运行中
- NLU backend：响应显示 `local_model:mlx`
- 身份：复用既有 `contract-e2e-*` 测试账号；未新增账号
- 请求接口：`POST /chat/`，SSE 对照使用 `POST /chat/stream`
- 可获得：RequestFrame、resolved constraints、tool trace、Reflect、menu progress、iteration、tool count、safety、最终答复
- Request Understanding 原始模型文本：NOT AVAILABLE
- prepare_context 的完整原始 profile/memory/context：NOT AVAILABLE；仅有聚合 metadata
- checkpoint 完整 state before/after：NOT AVAILABLE；通过相同 session 的前后行为和持久化历史间接观察
- token usage：NOT AVAILABLE

## 3. Totals

按 56 个附件 Case 统计：

| Result | Count |
|---|---:|
| PASS | 25 |
| FAIL | 20 |
| CRASH | 8 |
| UNSUPPORTED / NOT AVAILABLE | 3 |

额外 SSE 对照：正常 1 PASS；异常 1 CRASH，但异常流正确发送了终止 `done(error)`，未悬挂连接。

## 4. Complete Bug Matrix

| ID | Query / Scenario | Result | Bug Tag | Root Layer | Severity | Reproducible |
|---|---|---|---|---|---|---|
| A01 | 推荐一道鱼 | PASS | - | - | - | yes |
| A02 | 推荐四道鱼 | PASS | - | - | - | yes |
| A03 | 推荐六道家常菜 | PASS | - | - | - | yes |
| A04 | 两道素菜 | PASS | - | - | - | yes |
| A05 | 四道海鲜 | FAIL | NLU_CONSTRAINT_ERROR, RETRIEVAL_FILTER_ERROR | NLU/Search contract | P1 | yes |
| B01 | 推荐四道菜 | PASS | - | - | - | yes |
| B02 | 四个人安排午餐 | CRASH | REQUESTFRAME_VALIDATION_ERROR, STREAM_FAILURE | Understand/Menu contract | P0 | yes |
| B03 | 一家三口准备晚饭 | FAIL | NLU_SERVINGS_ERROR, NLU_COUNT_ERROR | NLU | P1 | yes |
| B04 | 六个人推荐三道菜 | PASS | - | - | - | yes |
| C01 | 水煮鱼材料 | FAIL | REQUESTFRAME_DATA_LOSS, NLU_FIELD_ERROR | NLU/Contract | P1 | yes |
| C02 | 水煮鱼怎么做 | PASS | - | - | - | yes |
| C03 | 水煮鱼多久 | FAIL | NLU_ENTITY_ERROR, NLU_FIELD_ERROR | NLU | P1 | yes |
| C04 | 水煮鱼材料和步骤 | FAIL | REQUESTFRAME_DATA_LOSS | NLU/Contract | P2 | yes |
| C05 | 礼貌语 + 柠檬蒸三文鱼步骤 | PASS | - | - | - | yes |
| D01 | “这个怎么做” | PASS | - | - | - | yes |
| D02 | “第二个怎么做” | FAIL | REFERENCE_RESOLUTION_ERROR | Short-term context | P1 | yes |
| D03 | “那个鲈鱼” | FAIL | REFERENCE_RESOLUTION_ERROR, NLU_ENTITY_ERROR | Short-term context/NLU | P1 | yes |
| D04 | “具体步骤呢” | PASS | - | - | - | yes |
| D05 | 鱼推荐后切换番茄牛腩 | PASS | - | - | - | yes |
| E01 | 两道荤菜 | PASS | - | - | - | yes |
| E02 | 两荤两素 | PASS | - | - | - | yes |
| E03 | 两荤两素一汤 | PASS | - | - | - | yes |
| E04 | 一荤一素一汤 | PASS | - | - | - | yes |
| F01 | 农村宴席 16 道 | PASS | - | - | - | yes |
| F02 | 10 人家庭聚餐配额 | PASS | - | - | - | yes |
| F03 | 未来三天每天两菜一汤 | UNSUPPORTED | CATEGORY_TAXONOMY_ERROR also observed | Temporal planning | - | yes |
| G01 | 喜欢鱼，推荐几道 | FAIL | NLU_SCOPE_ERROR | NLU | P2 | yes |
| G02 | 今天就想吃鱼，四道 | PASS | - | - | - | yes |
| G03 | 不喜欢姜 | FAIL | NLU_NEGATION_ERROR, RETRIEVAL_FILTER_ERROR | NLU/Safety filtering | P1 | yes |
| G04 | 不要辣、不要花椒 | FAIL | NLU_TASK_ERROR, NLU_NEGATION_ERROR | NLU | P1 | yes |
| G05 | 鱼是软偏好、别辣 | FAIL | NLU_TASK_ERROR, NLU_COUNT_ERROR, NLU_CONSTRAINT_ERROR | NLU | P1 | yes |
| H01 | 花生过敏，四道菜 | PASS | - | - | - | yes |
| H02 | 喜欢宫保鸡丁但花生过敏 | FAIL | REQUESTFRAME_DATA_LOSS | NLU/Contract | P1 | yes |
| H03 | 过敏与正宗宫保鸡丁冲突 | FAIL | REQUESTFRAME_DATA_LOSS | NLU/Contract | P1 | yes |
| H04 | 今天不想吃鱼 → 四道鱼 | FAIL | NLU_NEGATION_ERROR | NLU | P1 | yes |
| H05 | 永久花生过敏 → 下一轮 | FAIL | NLU_NEGATION_ERROR, MEMORY_SCOPE_ERROR | NLU/Memory contract | P1 | yes |
| I01 | 媳妇不辣，两人晚饭 | CRASH | REQUESTFRAME_VALIDATION_ERROR | Understand/Menu contract | P0 | yes |
| I02 | 儿子不姜，三口午饭 | CRASH | REQUESTFRAME_VALIDATION_ERROR | Understand/Menu contract | P0 | yes |
| I03 | 自己想吃鱼，四人午饭 | CRASH | REQUESTFRAME_VALIDATION_ERROR | Understand/Menu contract | P0 | yes |
| I04 | 不辣 + 鱼偏好，两人晚饭 | CRASH | REQUESTFRAME_VALIDATION_ERROR | Understand/Menu contract | P0 | yes |
| I05 | 不辣 + 不姜 + 鱼，四人午饭 | CRASH | REQUESTFRAME_VALIDATION_ERROR, STREAM_FAILURE | Understand/Menu contract | P0 | yes |
| I06 | 家属花生过敏 + 自己喜欢花生 | CRASH | REQUESTFRAME_VALIDATION_ERROR | Understand/Menu contract | P0 | yes |
| J01 | 四道鱼 → Crash → 四道鱼 | PASS | no state pollution reproduced | Recovery/State | - | yes |
| J02 | 宴席 → Crash → 宴席 | PASS | no state pollution reproduced | Recovery/State | - | yes |
| J03 | 新 conversation 对照 | PASS | - | State | - | yes |
| K01 | 不辣 → 普通菜 → 可吃辣 | FAIL | NLU_TASK_ERROR, NLU_NEGATION_ERROR | NLU/Constraint lifecycle | P1 | yes |
| K02 | 今天不想吃鱼 → 四道鱼 | FAIL | NLU_NEGATION_ERROR | NLU | P1 | yes |
| K03 | 菜单 → 水煮鱼步骤 | PASS | - | State isolation | - | yes |
| L01 | Recipe DB timeout | UNSUPPORTED / NOT AVAILABLE | - | Non-destructive fault injection absent | - | no |
| L02 | 不存在菜名 | FAIL | NLU_TASK_ERROR | NLU | P2 | yes |
| L03 | 存在菜但步骤缺失 | UNSUPPORTED / NOT AVAILABLE | - | No safe fixture/injection | - | no |
| M01 | 本地不存在罕见菜怎么做 | FAIL | NLU_TASK_ERROR | NLU | P2 | yes |
| M02 | 相同工具重复 | PASS | no repeated call observed | Loop | - | yes |
| M03 | Budget graceful degradation | PASS | no budget exhaustion reached | Loop | - | yes |
| N01 | 整点不辣的鱼吃 | FAIL | NLU_TASK_ERROR | NLU | P2 | yes |
| N02 | 俩荤仨素再来汤 | FAIL | NLU_TASK_ERROR, MENU_QUOTA_ERROR | NLU/Menu | P1 | yes |
| N03 | 一家子四个人吃啥 | FAIL | REQUESTFRAME_CONTRACT_ERROR, RETRIEVAL_COUNT_ERROR | NLU/Reflect | P1 | yes |
| N04 | 娃不姜、老婆不辣、自己要鱼 | CRASH | REQUESTFRAME_VALIDATION_ERROR | Understand/Menu contract | P0 | yes |
| N05 | 清淡，最好有鱼 | FAIL | NLU_CONSTRAINT_ERROR, RETRIEVAL_FILTER_ERROR | NLU/Search | P1 | yes |

## 5. Representative Detailed Records

### TEST B02 / I01–I06 / N04 — Meal arrangement crash

- Expected semantic understanding: recommendation/menu task; servings extracted; participant preferences represented or explicitly declared unsupported.
- Observed RequestFrame: NOT AVAILABLE because exception occurs while fallback understanding constructs the frame.
- Planner / Tool / Reflect: NOT REACHED.
- Log evidence: `extract_menu_planning_requirements` constructs `MenuPlanningRequirements(category_quotas=())`; Pydantic rejects a tuple shorter than one item.
- HTTP result: 500, generic internal error.
- SSE result: `accepted`, `progress: understand_request`, `error: stream_failed`, `done: error`.
- Status: CRASH.
- Diagnosis confidence: HIGH.
- Suggested Fix Direction: distinguish “meal recommendation without quotas” from “quota menu planning” before constructing the non-empty quota value object; convert contract validation failures into a clarification or ordinary recommendation, not an uncaught 500.

### TEST A05 — Seafood

- RequestFrame: `count=4`, `food_category=seafood`, but also `target.ingredient=海鲜` and required `include_ingredient=海鲜`.
- Planner args: carried seafood plus literal ingredient requirement.
- Tool result: 0/4 although catalog contains fish and shrimp dishes.
- Final: reports zero verified recipes.
- Status: FAIL, P1.
- Root cause: category noun duplicated as a literal ingredient, making valid seafood fail the ingredient filter.
- Diagnosis confidence: HIGH.
- Suggested Fix Direction: make category entities and literal ingredients mutually exclusive in the request contract.

### TEST C03 — Requested time

- RequestFrame target: `水煮鱼要`; requested field: `time`.
- Final: three unrelated ordinary recommendations, no cooking time.
- Status: FAIL, P1.
- Root cause: detail suffix stripping retained “要”; failed exact lookup then downstream route degraded to recommendation instead of field-specific NOT_FOUND/FIELD_MISSING.
- Diagnosis confidence: HIGH.
- Suggested Fix Direction: validate resolved entity against catalog before acceptance and preserve requested-field failure semantics through Planner/Responder.

### TEST D02 — Ordinal reference

- Turn 1 list order: 豆豉蒸鲈鱼, 柠檬蒸三文鱼, 清蒸鲈鱼.
- Turn 2: “第二个怎么做？”
- Resolved target: 清蒸鲈鱼 (third item), not 柠檬蒸三文鱼.
- Status: FAIL, P1.
- Root cause: recent entity ordering differs from rendered response ordering.
- Diagnosis confidence: HIGH.
- Suggested Fix Direction: persist the exact rendered entity sequence with the assistant turn and resolve ordinals only against that sequence.

### TEST G03 — Negation reversal

- Input: 我不喜欢姜，推荐几道菜.
- RequestFrame: required `include_ingredient=姜`; no exclusion.
- Final: 双椒鸡丁、姜汁蒸鸡腿、姜葱牛肉，全部含姜.
- Status: FAIL, P1.
- Root cause: negative preference was normalized as positive required ingredient.
- Diagnosis confidence: HIGH.
- Suggested Fix Direction: perform negation/scope classification before generic ingredient extraction; forbid the same mention from becoming a positive include when governed by negative language.

### TEST G04 / K01 — Negative-only request

- Inputs: “不要辣，也不要花椒” / “今天不吃辣”.
- Observed: interpreted as recipe-detail requests for 花椒鸡丝 / 酸辣土豆丝 and returned recipes containing precisely the rejected ingredients.
- Status: FAIL, P1.
- Root cause: catalog entity matching outranks negation/task semantics.
- Diagnosis confidence: HIGH.
- Suggested Fix Direction: gate fuzzy recipe-entity resolution behind an already-established detail intent; negative-only turns should become constraints plus clarification/recommendation.

### TEST F01 / J02 — Complex menu and recovery

- RequestFrame: 16 total with quotas 3 cold, 2 hot, 4 vegetarian, 5 meat, 1 soup, 1 staple.
- Tool calls: 8; iterations: 2.
- Coverage: all quotas complete; 16 distinct selected recipes.
- Middle crash: multi-person meal request fails in understand_request.
- Repeated banquet in same session: again complete 16/16.
- Status: PASS for menu and recovery.
- Evidence against state pollution: selected recipes, coverage and budgets were reinitialized sufficiently for the repeated task.

## 6. Top Root Causes

1. Empty menu-quota contract constructed for unstructured meal requests  
Occurrences: 8 direct crashes  
Severity: P0

2. Negation and scope are applied after generic entity/ingredient extraction  
Occurrences: G03, G04, H04, H05, K01, K02 and related safety contract loss  
Severity: P1

3. NLU accepts structurally valid but semantically invalid RequestFrames  
Occurrences: A05, C01, C03, C04, G05, N03, N05  
Severity: P1

4. Participant-scoped preferences/allergies are not representable in the current RequestFrame  
Occurrences: I01–I06, N04 (masked by the earlier empty-quota crash)  
Severity: P1 after the P0 crash is removed

5. Rendered response order and stored recent-entity order diverge  
Occurrences: D02; D03 also shows ambiguous entity handling failure  
Severity: P1

## 7. P0/P1 Failure Chains

### Empty-quota crash

User asks to arrange a meal without explicit categories  
→ fallback detects menu-like wording  
→ produces zero category quotas  
→ constructs non-empty `MenuPlanningRequirements` contract  
→ Pydantic ValidationError in `understand_request`  
→ Planner and tools never run  
→ normal HTTP returns 500  
→ SSE returns `stream_failed` and terminates degraded.

### Negation reversal

User states “不喜欢姜”  
→ generic ingredient extractor finds 姜  
→ scope/negation is lost  
→ RequestFrame marks 姜 as required include  
→ Planner passes positive constraint  
→ retrieval preferentially returns ginger dishes  
→ final safety sees no represented exclusion  
→ confidently returns the inverse of user intent.

### Ordinal reference mismatch

Agent renders three recipes in order A, B, C  
→ recent context stores/returns entities in another order  
→ user asks for second  
→ resolver chooses C  
→ exact detail lookup succeeds  
→ fluent but wrong dish instructions are returned.

### Seafood zero-result

User requests seafood category  
→ NLU correctly adds seafood category  
→ NLU also incorrectly requires literal ingredient “海鲜”  
→ retrieval candidates contain 三文鱼/虾仁 rather than literal 海鲜  
→ all candidates filtered  
→ Reflect reports 0/4 partial despite available matches.

## 8. State Pollution Analysis

- J01: 4-fish PASS → multi-person CRASH → same-session 4-fish PASS with 4/4.
- J02: banquet PASS → multi-person CRASH → same-session banquet PASS with all 16 quotas.
- K03: menu planning PASS → recipe detail PASS; no coverage or selected IDs leaked.
- New-session A02/F01 controls were also normal.

Conclusion: `CHECKPOINT_STATE_POLLUTION`, `TURN_STATE_NOT_RESET`, `FAILED_RUN_RESUMED`, and budget leakage were **not reproduced**. Because complete checkpoint internals are not exposed, this conclusion is behavioral rather than a direct state dump.

## 9. Multi-turn Analysis

- Stable: direct pronoun after one recommendation, repeated “具体步骤”, explicit task switch.
- Broken: ordinal reference uses wrong ordering; ambiguous “那个鲈鱼” neither clarifies nor binds cleanly, producing malformed target `那个鲈鱼要什么` and an external “蒸鲈鱼” result.
- Constraint lifecycle: explicit new fish request is not polluted by prior “今天不想吃鱼”, but the first negative turn itself is malformed.

## 10. Safety Analysis

- H01 successfully excludes peanut recipes and passes final safety.
- H02/H03 give a safe refusal/no-match, but current RequestFrame loses the explicit allergy. Earlier H01 persisted peanut memory on the shared test account, so persistent memory may have masked the contract defect.
- G03/G04 demonstrate that preference/exclusion safety can fail before final safety because the prohibition never reaches resolved constraints.
- Participant-scoped allergy I06 cannot be evaluated beyond understanding because it crashes first.

## 11. Planner / Tool Contract Analysis

- Standard counted recommendation and menu quotas propagate correctly.
- F01 reaches complete coverage through 8 calls and 2 iterations without premature completion.
- Tool trace is adequate for names, args, status and count.
- Main observed failures usually occur before Planner; A05 is the clearest NLU-to-tool argument contamination.
- F03 exposes an additional taxonomy issue: “不出汤的醋溜白菜” is classified as soup, likely from lexical substring matching. Because multi-day planning itself is unsupported, this is recorded separately rather than treating the whole request as a supported failure.

## 12. Loop / Budget Analysis

- No same-tool/same-args/same-result repetition was observed.
- No tested request exhausted max iterations, calls or tokens.
- Complex menu stopped after completion.
- Missing local recipe requests were incorrectly routed out-of-scope before exercising the intended NOT_FOUND loop, so M01 cannot validate deep retry behavior.
- Loop budget internals beyond iteration/tool count: NOT AVAILABLE.

## 13. Stable Regression Baseline

Future changes should not break:

- A01 one fish, A02 four fish, A03 six dishes, A04 two vegetarian dishes.
- B01 four dishes and B04 simultaneous servings=6/count=3.
- C02 recipe steps and C05 polite recipe-step query.
- D01 single-item pronoun, D04 repeated step reference, D05 explicit task switch.
- E01–E04 standard menu quotas.
- F01 16-dish banquet and F02 family gathering quotas.
- G02 current-turn hard fish constraint.
- H01 current peanut allergy filtering.
- J01/J02 failure recovery behavior.
- K03 menu-to-detail state isolation.
- Normal SSE must end with `done(status=ok)`; failed SSE must end with `done(status=error)`.

## 14. Recommended Fix Order

### P0-1 Empty-quota state construction

Why: causes deterministic 500 before Agent execution for common meal requests.  
Affected: B02, I01–I06, N04.  
Risk: a large class of normal user requests remains unusable; participant handling cannot even be assessed.

### P1-1 Negation and scope before entity extraction

Why: current behavior can return exactly what the user rejects.  
Affected: G03, G04, H04, H05, K01, K02.  
Risk: dietary preference and potentially safety constraints silently invert.

### P1-2 RequestFrame semantic validation

Why: schema-valid frames can contain incompatible meanings such as seafood category plus literal ingredient 海鲜, or detail task without target/fields.  
Affected: A05, C01, C03, C04, G05, N03, N05.  
Risk: fluent but unrelated answers and false zero-results.

### P1-3 Participant-scoped requirements

Why: wife/child/self requirements currently have no explicit owner/scope model.  
Affected: I01–I06, N04 after crash removal.  
Risk: one participant's allergy may be treated as preference or applied to the wrong people.

### P1-4 Render-order reference contract

Why: ordinal references must resolve against what the user actually saw.  
Affected: D02, D03.  
Risk: plausible instructions for the wrong dish.

### P2-1 Natural-language robustness and unsupported capability response

Why: colloquial quotas and multi-day planning currently produce misleading partial results.  
Affected: F03, N01–N05, L02, M01.  
Risk: poor trust and inability to distinguish unsupported from no results.

## 15. Mutation Declaration

- Source code modified: **NO**
- Production configuration modified: **NO**
- Database schema or recipe data modified: **NO**
- Database chat/auth side effects: **YES** — logging in created refresh-token state and real chat calls persisted test sessions/messages/memory exactly as the product normally does. No manual SQL writes or destructive operations were performed.
- Test-only artifacts created: **YES**, under `evaluation_results/` only.

