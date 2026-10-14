# Agent 第四项：检索质量与消融（第 9/9 份）

日期：2026-10-10。对应实习项目补充计划的最后一项。本报告区分已验证的代码修复、本地参考算法消融和外部服务验证；生产嵌入/重排质量尚未验证，不能用本地数据代替。

## 1. 结论与范围

已修复混合检索分数过滤、BM25 租户过滤时机、Agent 知识工具的租户传递、嵌入乱序与缺失响应、重复 RRF 投票、重排结果校验与候选预算，以及引用片段归因。增加固定语料、可重复消融、针对性与全量回归。此前 L08 鱼类组胺回答的核心事实错误，在三次完整 Agent 运行和六次给定证据的回答网关运行中均未复现。

实际嵌入请求返回 HTTP 404：原有效配置把 `text-embedding-v4` 指向 `api.deepseek.com`。未取得真实向量，未继续调用生产重排，未测试 Milvus ANN；因此本项生产检索效果验收仍待可用服务配置。代码现已避免将聊天服务的地址及凭据无条件继承给其他供应商，但没有编辑日常 `.env` 或自行更换模型/凭据。

## 2. 固定数据与实验方法

语料：[retrieval_v1.json](../../tests/evaluation/datasets/retrieval_v1.json)，[校验和](../../tests/evaluation/datasets/retrieval_v1.sha256)。10 篇短文，20 条人工标注查询，每条一个相关文档；每主题两问分别进入 dev/test，各 10 问。D01 是核对 [FDA 原文](https://www.fda.gov/food/hfp-constituent-updates/fda-issues-final-compliance-policy-guide-scombrotoxin-histamine-forming-fish-and-fishery-products) 后编写的简短中文摘要，其余是明确标注的合成厨房制度/菜谱。无真实用户文档、账户或凭据。

**这不是独立真实用户测试集**：dev/test 共享主题，短文较容易命中；没有大规模负例、多相关文档和真实上传文档分布。数据在实验前落盘并校验，相关标签不进入排序模型。以文档 ID 去重计算 Recall@1/3 与 MRR@1/3：Recall 衡量标注相关文档是否入选，MRR 衡量第一个相关文档的排名。全部逐问结果及失败样本保留。

四组复用 DocumentKnowledgeService 及真实 SQLite FTS5 BM25 实现：

- BM25：词法检索，不应用向量相似度阈值。
- 向量参考：仅用语料文档拟合字符 1–2 gram TF-IDF，查询只做 transform，本地精确余弦排序。
- 混合：两路排名经现有 RRF 融合。
- 混合＋参考重排：候选按查询 token 覆盖率重排。

后面三组的向量/重排组件是**本地参考算法**，不是 `text-embedding-v4` / `qwen3-rerank`，不能据此判断生产语义模型优劣。参考缓存与 provider 缓存禁止混用。脚本也支持显式 opt-in 的真实供应商调用，并在重排静默回退时拒绝将结果记为成功实测。向量存储始终是本地精确余弦参考，不测 Milvus 性能。

## 3. 消融结果与失败分析

### 保留原相似度阈值 0.7：复现并验证过滤缺陷

修复前报告加载 Git HEAD 中原 DocumentKnowledgeService；其他评测条件和向量缓存相同。它是原用例代码的隔离重放，不是修复前线上流量测量。原源码 SHA 写入报告。

| test，10 问 | 修复前 Recall@3 | 修复后 Recall@3 | 修复后 MRR@3 |
| --- | ---: | ---: | ---: |
| BM25 | 1.000 | 1.000 | 0.933 |
| 向量参考 | 0.000 | 0.000 | 0.000 |
| 混合 | 0.000 | 1.000 | 0.933 |
| 混合＋参考重排 | 0.000 | 1.000 | 0.933 |

原实现融合后继续检查原 `score >= 0.7`，词法分数与向量分数混用，使 BM25 证据全部丢失。修复将阈值放到向量通道融合之前。参考向量为零的原因是 TF-IDF 的分数低于该阈值，**不是生产嵌入模型召回为零**。没有根据本地 TF-IDF 改动生产阈值。

证据：[修复前](../../evaluation_results/agent_retrieval_before.json)、[修复后](../../evaluation_results/agent_retrieval_ablation.json)。

### 向量参考阈值设为 0：组件比较诊断

| test，10 问 | Recall@1 | Recall@3 | MRR@3 |
| --- | ---: | ---: | ---: |
| BM25 | 0.900 | 1.000 | 0.933 |
| 向量参考 | 1.000 | 1.000 | 1.000 |
| 混合 | 0.900 | 1.000 | 0.950 |
| 混合＋参考重排 | 0.900 | 1.000 | 0.933 |

dev 四组均为 1.000。这个容易的数据集上，混合未优于向量参考，参考重排还降低了 MRR，因此**不宣称增加组件一定带来提升**。证据：[无阈值参考消融](../../evaluation_results/agent_retrieval_reference_unfiltered.json)。

保留的失败/改进线索：

- 在 0.7 条件下，向量参考 20 问均未进入结果；应对实际向量分布做独立阈值校准，不能移植参考阈值。
- test 的 BM25 / 重排首位有错配，@3 仍命中；报告的 `rows` 可复核每个查询、相关 ID、返回 ID 及 chunk ID。不要只报 Recall@3。
- 生产 API 404 是配置问题，不记成模型的零召回或成功消融。
- 当前数据不足以检验复杂否定、多段证据或不可回答问题；局部权限/空证据行为由单独测试覆盖，不混入上述命中率。

## 4. 具体修改

| 层 | 修改与目的 |
| --- | --- |
| Knowledge 应用用例 | 向量阈值在融合前生效；关闭过滤确实保留低分向量；查询结果再次检查租户；显式向量过滤请求不并入 BM25；限制重排候选数；只允许重排已召回的原始片段 |
| SQLite 适配器 | 租户条件以参数化 SQL 放在 LIMIT 前；默认只查 public，防止跨租户行抢占召回名额 |
| RRF | 同一路的同一片段仅投票一次，不因重复行放大权重 |
| 嵌入适配器 | 按响应 index 对齐原文本；拒绝缺失、重复、越界、维度错误和非有限数值；不补零向量掩盖失败 |
| 重排适配器 | 校验整数索引、有限分数；去重；保留零分；自定义/Jina/Voyage 共用结果解析 |
| Agent 工具与 HTTP | 已认证 Principal 在普通聊天、SSE 和恢复入口绑定请求范围租户，工具只读取可信范围；schema 拒绝模型附加租户参数；结束时复位，内部未绑定调用仅能访问 public |
| 引用契约 | AnswerSource 新增可空 document_id / chunk_id；去重保留不同片段与调用的归因，原 source/tool/call_id 字段兼容 |
| 回答网关 | 明确检索文档是数据，不能改变规则、权限或触发工具；要求知识回答引用真实片段、缺证据时说明不足；增加 FDA 核对过的组胺安全规则 |
| 配置 | 不把 LLM 凭据默认发送给其他主机；缺失嵌入地址默认 DashScope；仅同主机允许继承凭据，显式配置仍需运维确认；嵌入客户端不自行回退全局 OPENAI_API_KEY |

限制：`filter_expr` 是向量适配器语法，词法端口没有同等表达式解析器，采用关闭该请求词法合并的保守实现。来源集合仅表明返回了哪些证据，不证明每句话都被证据支持；本次没有引入逐句引用验证器。BM25 的语料统计仍是共享索引的全局统计，结果访问已隔离，不声称完成索引层物理隔离。

## 5. 实际回答与食品安全核对

FDA 明确说明，鱼类组胺一旦形成，不能通过清洗、冷冻或加热去除；及时冷却及时间/温度控制用于防止积累。[原文](https://www.fda.gov/food/hfp-constituent-updates/fda-issues-final-compliance-policy-guide-scombrotoxin-histamine-forming-fish-and-fishery-products)

- L08 “为什么做鱼要彻底加热？”：3 次完整 HTTP Agent 实测均明确说加热不能消除已形成的组胺，并说明没有检索到相关文档；不是检索成功，也不算完整问题有充分证据。该脚本的三系统结构评分为 9/9，不能替代事实审阅。本报告的逐条事实核对由助手完成，并非独立人工评审。
- 给定 D01_0 FDA 摘要：两问各三次，真实生产回答网关共 6 次均给出正确核心组胺结论并引用 D01_0，API 来源也正确关联到文档 D01 与该片段。
- 这些回答仍有微生物等附带解释，不全由该短摘要支持。6/6 表示所检查的核心事实和片段归因通过，不表示完整答案的全部陈述有据。

证据：[完整 L08 实测](../../evaluation_results/agent_retrieval_histamine_live.json)、[给定证据的网关实测](../../evaluation_results/agent_retrieval_grounded_answers.json)、[定向事实审阅](../../evaluation_results/agent_retrieval_manual_review.json)。后者是**手动提供证据的回答层检查**，不算从生产索引端到端检索。

恶意文档测试完全本地运行：验证注入文本仍在不可信 payload、不会升级为 system 指令，以及重排器不能替换正文或引入新证据。这是边界契约测试，不能证明任意真实模型对所有提示注入都安全。

## 6. 测试与架构审阅

针对性测试：[test_retrieval_quality.py](../../tests/refactor/test_retrieval_quality.py)，24 项覆盖分数通道、分页前权限过滤、并发 scope、HTTP/SSE/恢复 scope、伪造参数、嵌入索引、重排分数与预算、引用归因、切分原文、固定标签、供应商凭据边界和注入 payload。

**最终结果：24 项针对性测试通过；全量 510 passed、25 skipped；Ruff、Mypy（307 个源文件）与 git diff --check 通过；前端 10 项测试及 Vite 生产构建通过。**

全量与静态检查结果以 [validation.json](../../evaluation_results/agent_retrieval_validation.json) 和 [JUnit](../../evaluation_results/agent_retrieval_regression.xml) 为准；跳过项是需要额外配置的外部/集成测试，不记为已通过。前端现有测试与生产构建同时验证新增来源字段不会影响现有流程。

架构审阅结论：

1. 排名/过滤规则留在 knowledge 用例，FTS SQL、供应商响应校验留在基础设施适配器；没有把 DB 或 HTTP 客户端加入 Agent 图。
2. 身份由 HTTP 认证 Principal 注入，模型工具参数没有身份决定权。scope 遵循现有请求范围 ContextVar 模式，不在进程单例上保存可变租户。
3. 引用扩展只增加可空字段；不新增业务表、审批状态或第二套检索业务逻辑。
4. 发现并修复证据模块独立导入时的包初始化循环：orchestration 的图入口按需导入，原导出名称兼容，架构回归通过。
5. 评测缓存、精确余弦存储、TF-IDF 和参考重排只在脚本中，不进入生产依赖装配，不对线上效果或吞吐作虚假推断。

## 7. 复现

在项目环境执行；`python` 应为已安装依赖的项目 Python。所有评测使用临时 FTS/内存存储，不接触日常数据库、上传目录或 Milvus 集合。

```bash
make test-agent-retrieval

# 固定参考消融，零外部调用
python scripts/evaluate_agent_retrieval.py --reference \
  --cache evaluation_results/agent_retrieval_reference_cache.json

# 原用例隔离重放，必须保留含原实现的 Git HEAD
python scripts/evaluate_agent_retrieval.py --reference --baseline \
  --cache evaluation_results/agent_retrieval_reference_cache.json \
  --output evaluation_results/agent_retrieval_before.json

# 仅用于观察参考向量阈值，不改变生产配置
python scripts/evaluate_agent_retrieval.py --reference --threshold 0 \
  --cache evaluation_results/agent_retrieval_reference_unfiltered_cache.json \
  --output evaluation_results/agent_retrieval_reference_unfiltered.json

# 配好有效的 EMBEDDING / RERANK 服务后，明确允许外部调用
python scripts/evaluate_agent_retrieval.py --allow-provider-calls

# 回答网关核对，只发送固定公开 FDA 摘要
python scripts/evaluate_agent_retrieval_answer.py --allow-provider-calls
```

`--baseline` 在以后提交修复后会读取新的 HEAD，不能再当成原实现；报告保留当前原源码 SHA 与冻结输出作为审计证据。参考算法需要项目环境中已有的 scikit-learn，未加入传统后端运行依赖。

## 8. 尚待生产验收与文档交付

[服务状态记录](../../evaluation_results/agent_retrieval_provider_status.json) 保留初次请求及配置修复后的状态，不包含密钥。初次外部调用被自动审批审查拒绝：载荷含模拟跨租户/秘密样式内容，实际未执行。已改成严格 public 的合成语料并获准执行；本地权限/注入测试没有发送给供应商。

仍需运维在本地配置与所选嵌入及重排供应商匹配的凭据，然后运行真实消融，再用隔离 Milvus 集合验证存取、权限及索引参数。当前不能声称生产 RAG 的召回质量已经验收，也不能声称重排比 BM25 更好。

本文件是原计划第 9 份文档：技术栈 1 份、传统后端 4 份、Agent 4 份均已形成对应报告。后续生产服务补齐须由用户确认继续，不自动扩展成下一轮项目优化。
