# Worldpay77 Operations Manual 1.0

> 本文件描述的是 Worldpay77 真正要建设的目标系统，不是当前代码已经全部实现的现状。
> 当前代码已经有多 Agent 流水线、Web UI、Perplexity 手动回填、Chairman Brief、Red Team Audit；但目标不是一个"投资分析辅助工具"，而是一家本地运行、每天沉淀、可复盘、会进化的 AI Native 投资公司。

## 1. 核心定位

Worldpay77 是 Nepha 的 AI Native 投资公司。

它不是让 AI 写几份股票分析报告，也不是把多个 Agent 串成一条命令行流水线。它的目标是把一家投资公司的核心组织能力本地化、结构化、可追踪化：

- K deep / K deep负责提出真正值得研究的问题。
- Perplexity Deep Research 是公司的首席研究员，负责把关键问题研究透。
- 三位投资大佬 Agent 负责从不同投资哲学出发独立判断。
- Chairman 是首席投资官，负责在分歧中给出可执行裁决。
- Red Team 是反对派合伙人，负责攻击证据链、假设链和历史类比。
- Nepha 是 GP，保留最终投资决策权。

一句话：

**K deep 的选题能力 + Perplexity 的深度研究 + 三位投资大佬的方法论 + Chairman 的裁决能力 + Red Team 的反对能力 + 每天复用的知识库 = Worldpay77。**

## 2. 当前代码的真实状态

当前系统已经完成了一个可运行骨架：

- Web UI 可以在 `http://127.0.0.1:7777` 启动。
- 股池由 `data/stock_pool/master_pool.yaml` 管理。
- Research Agent 会扫描 HK / US 主股池，基于公开价量触发 `research_signal` 和 Perplexity prompt。
- Nepha 可以在"深度研究"页复制 prompt，到 Perplexity 手动做 Deep Research，再把答案回填到 `data/perplexity_results/`。
- 三位交易 Agent 会读取 K deep 信号、方法论、价量数据、Perplexity 回填状态，并输出 recommendation。
- Chairman 会聚合三位 Agent 的观点，生成 Morning / Evening Brief。
- Red Team 会做规则审计、风险完整性检查和方法论挑战。
- Orchestrator 会记录运行历史和产物路径。

但这仍然只是"第一阶段可运行系统"，不是目标态投资公司。

当前最核心的差距：

- Research Agent 已把 `methodologies/research_system_v0.3.md` 的 Gate 1-7 接入 Perplexity prompt 和 `signal_fingerprint`，并会在生成新 prompt 前读取历史知识缺口，避免重复研究已确认事实。
- Perplexity 回填只是当天 Agent 的上下文，不会自动沉淀成长期可检索的公司知识。
- 三位投资大佬 Agent 仍保持静态方法论，但 Chairman 已能读取 Partner Performance Log；第一阶段不把表现反馈直接喂回三位 Agent，避免污染方法论 DNA。
- Chairman 已具备 `final_verdict`、相似案例、历史冲突、Agent 表现权重和 Red Team 后二次裁决规则；后续主要增强真实已验证样本。
- Red Team 已从规则审计升级到可读取历史反例、相似案例和知识库冲突；后续主要增强 Red Team 反对意见的验证闭环。
- 系统已形成股票记忆、相似案例、Agent 表现、Decision Verification 和 Partner Review 的第一版长期记忆层；后续需要更多真实样本喂养。

## 3. 组织架构

### 3.1 GP: Nepha

Nepha 不是普通用户，而是 GP。

Nepha 的职责：

- 维护股池和方法论方向。
- 决定哪些 Perplexity prompt 值得手动深度研究。
- 阅读 Chairman 裁决和 Red Team 反对意见。
- 做最终投资决策。
- 定期复盘系统表现，决定是否升级方法论或调整 Agent 权重。

系统里的 AI 不替 Nepha 下单，不接券商，不做自动交易。

### 3.2 研究部: K deep / K deep

研究部的核心任务不是"发现涨跌幅"，而是"提出值得 Perplexity 研究的好问题"。

K deep 的当前权威源文件是 `methodologies/research_system_v0.3.md`。它来自 `nepha-investment-system-v0.5.zip`，是对 K deep 研究方法论资产的压缩总结；外部 `methodology_research_system.md` 是 v0.2 的前序材料，不覆盖仓库内 v0.3。

目标态 Research Agent 应该分三层工作：

1. 公开信号层：保留当前价量、成交量、跳空、连续涨跌等扫描能力，用它识别市场正在说话的时刻。
2. K deep 框架层：把信号放进赛道、商业模式、创始人、竞争格局、非连续变化、渗透率、成本曲线、供需结构、监管变化、资本市场预期差中重新提问。
3. Perplexity prompt 层：把最重要的问题转成结构化 Deep Research prompt，按优先级交给 Nepha 手动研究。

Research Agent 不输出交易建议。它只输出：

- `research_signal`
- `routing_recommendation`
- `perplexity_prompt_brief`
- 需要补充研究的问题清单

### 3.3 首席研究员: Perplexity Deep Research

Perplexity 在系统里不是普通搜索工具，而是首席研究员。

核心原则：

- 系统不自动调用 Perplexity。
- Nepha 手动把 prompt 放进 Perplexity Deep Research。
- Perplexity 的结果必须回填到系统，并保留原始报告。
- 没有 Perplexity 深度研究背书的股票，不能升级成高置信度交易判断。
- Perplexity 的研究不能一次性消费，必须沉淀到知识库。

回填后的系统动作：

- 保存原始研究报告。
- 提取公司级结论。
- 提取行业级结论。
- 提取关键证据、反证、未验证事项。
- 更新股票档案、行业档案、市场叙事库。
- 把这次研究和后续 Chairman 裁决、Red Team 反对意见、价格验证结果绑定。

### 3.4 投资委员会: 三位投资大佬 Agent

三位 Agent 不是同一个 LLM 的三种语气，而是三种不同投资哲学的合伙人。

- F partner Agent：逆向赔率、杀跌类型、关注度/购买度错配、赔率优先。
- W partner Agent：单边翻倍、三选三型三刀三率、协同验证、核心问题压缩。
- G partner Agent：高确定性、护城河、进化力、熵减力、95% 主观胜率、贝叶斯门槛。

目标态输入不应只包括当天信号，还必须包括：

- 当天 K deep research_signal。
- Perplexity 原始研究和结构化摘要。
- 该股票历史研究档案。
- 同行业历史研究档案。
- 当前市场叙事背景。
- 本 Agent 自己过去类似判断的准确率和失误模式。

目标态输出不只是 `watch / avoid / abstain`，而是：

- 当前试运行期：仍可限制为 `watch / avoid / abstain`，用于安全校准。
- 正式决策期：允许输出 `long` 倾向和仓位建议，但必须经过 Chairman 和 Red Team，再由 Nepha 决定。

### 3.5 首席投资官: Chairman

Chairman 不能只做投票统计。

目标态 Chairman 必须回答：

- 三位大佬各自看到了什么？
- 谁的判断和 Perplexity 研究最一致？
- 谁的判断和历史相似案例更一致？
- 哪个分歧是方法论差异，哪个分歧是真风险？
- Red Team 最可能攻击哪里？
- 如果必须给 Nepha 一个操作导航，是什么？

目标态 Chairman 输出应包含：

- `final_verdict`: `act / wait / reject / research_more`
- `action_route`: 可执行操作导航，例如观察、继续研究、试错仓、放弃、进入下次复盘。
- `decision_chain`: 为什么更信任某个 Agent 的判断。
- `dissent_summary`: 关键反对意见。
- `history_context`: 与历史研究、历史裁决、历史结果的关系。
- `confidence`: 对裁决本身的置信度，而不是简单平均三位 Agent 的 confidence。

Chairman 不是 Nepha，但它必须有担当。它可以说"我认为应该等"，也可以说"这值得进入试错仓观察"，但最终是否执行仍由 Nepha 决定。

### 3.6 反对派合伙人: Red Team

Red Team 不能只检查格式、source_url、schema 和 trial-run 规则。

目标态 Red Team 要做实质性反对：

- 攻击 Perplexity 报告的证据链。
- 攻击三位 Agent 的关键假设。
- 攻击 Chairman 的历史类比。
- 查找知识库中与本次结论冲突的旧研究。
- 查找同类信号过去失败的案例。
- 明确告诉 Nepha："这个结论最脆弱的地方在哪里？"

目标态 Red Team 输出应包含：

- `strongest_objection`
- `evidence_chain_risk`
- `missed_counter_evidence`
- `historical_failure_pattern`
- `what_must_be_true_for_chairman_to_be_right`
- `what_would_invalidate_this_decision`
- `red_team_verdict`: `block / challenge / monitor / no_major_objection`

## 4. 最核心的基础设施: Investment Knowledge Base

让系统从工具变成公司的关键，是知识沉淀层。

当前系统每天生成很多文件，但这些文件主要按日期散落在 `data/` 下。目标态需要一个 Investment Knowledge Base，把每天产物转成可检索、可复用、可复盘的公司资产。

### K deep 股票档案

每只进入研究流程的股票，都要有长期档案：

- 基本信息和股池状态。
- 历次 K deep research_signal。
- 历次 Perplexity 原始研究。
- Perplexity 结构化摘要。
- 三位 Agent 历次判断。
- Chairman 历次裁决。
- Red Team 历次反对意见。
- 后续价格走势验证。
- 当前未关闭的关键问题。

下一次同一只股票再次触发时，Agent 必须知道之前研究过什么。

### 4.2 行业知识库

Perplexity 每次研究不仅属于某只股票，也属于一个行业或主题。

行业知识库保存：

- 行业结构变化。
- 竞争格局变化。
- 渗透率、成本曲线、供需结构变化。
- 监管变化。
- 关键公司对照。
- 本行业过去判断中哪些变量最容易误判。

### 4.3 市场叙事库

市场叙事库保存跨股票、跨行业的背景判断：

- 当前市场主线。
- 利率、流动性、风险偏好。
- AI、软件、港股互联网、生物科技等主题热度。
- 哪些叙事正在加强，哪些正在失效。

Chairman 做历史类比时，必须知道两次判断发生在什么市场叙事中。

### 4.4 Partner Performance Log

每位大佬 Agent 要有成长档案：

- 总体判断准确率。
- 按行业的准确率。
- 按信号类型的准确率。
- `watch` 后上涨、下跌、无效的比例。
- `avoid` 后是否真的避开了风险。
- 哪些场景下过度保守。
- 哪些场景下过度乐观。
- 最近 30 天 / 90 天状态。

这个档案不是为了替代方法论，而是让 Agent 知道自己的盲区。

### 4.5 Decision Verification Log

每次 Chairman 裁决都必须进入验证队列。

验证周期可以是：

- 1 天：是否有明显事件验证或打脸。
- 7 天：短期价格和新闻反馈。
- 30 天：研究判断是否仍成立。
- 90 天：核心 thesis 是否被证实或证伪。

验证结果反哺：

- 股票档案。
- 行业知识库。
- Chairman 权重。
- Red Team 反对标准。
- Partner Performance Log。

## 5. 每日工作流

目标态日常流程：

```text
早盘前 / 收盘后
      ↓
Research Agent 扫描股池
      ↓
K deep / K deep 框架生成研究问题
      ↓
系统检索知识库
      ↓
生成 Perplexity Deep Research prompt
      ↓
Nepha 手动提交 Perplexity
      ↓
Perplexity 报告回填
      ↓
系统提取结构化知识并入库
      ↓
三位投资大佬 Agent 独立分析
      ↓
Chairman 给出带逻辑链的裁决
      ↓
Red Team 提出最强反对
      ↓
输出 Final Brief
      ↓
Nepha 最终拍板
      ↓
后续进入验证和复盘队列
```

## 6. 最终报告应该长什么样

最终报告不是"今天有几条 signal"。

它应该让 Nepha 快速知道：

- 今天最值得看的股票是哪几只？
- 哪些只是噪音？
- 哪些需要继续 Perplexity 深研？
- 哪些已经研究足够但仍不值得动？
- 哪些值得进入观察或试错？
- 这次判断和过去有什么不同？
- 最强反对意见是什么？
- 如果错，最可能错在哪里？

目标态 Final Brief 结构：

```text
1. 今日结论
   - act / wait / reject / research_more
   - 不是交易指令，而是 GP 决策导航

2. 重点标的
   - 股票
   - 触发原因
   - Perplexity 研究结论
   - 三位 Agent 观点
   - Chairman 裁决
   - Red Team 最强反对

3. 历史记忆
   - 这只票以前研究过什么
   - 当时怎么判断
   - 后来验证结果如何
   - 今天的新信息改变了什么

4. 待研究问题
   - 必须跑 Perplexity 的问题
   - 可以跳过的问题
   - 已关闭的问题

5. 复盘队列
   - 1 天后验证什么
   - 7 天后验证什么
   - 30 天后验证什么
   - 90 天后验证什么
```

## 7. Agent 如何成长

Agent 成长不是让 prompt 越写越长，而是让系统把经验转成下一次判断的输入。

### 7.1 短期成长

Perplexity 回填后，第二天同一股票或同行业触发时，系统能自动检索到昨天的研究。

### 7.2 中期成长

每 30 天，系统统计三位 Agent 在不同场景下的表现：

- 哪位在软件股上更准？
- 哪位在港股互联网上更保守但更安全？
- 哪位对生物科技误判更多？
- 哪类 Red Team 反对意见后来被证明有价值？

### 7.3 长期成长

每 90 天，系统做一次投资委员会复盘：

- 哪些方法论规则需要升级？
- 哪些阈值过严或过松？
- Chairman 是否过度依赖某位 Agent？
- Red Team 是否经常误报？
- Perplexity prompt 质量是否提高？

## 8. 分阶段实施路径

### P0: 把当前系统改成"有记忆的系统"

目标：Perplexity 回填不再只服务当天。

要做：

- 新增 `knowledge_store` 模块。
- 每次 Web UI 保存 `PR-*_filled.yaml` 后，自动生成结构化 knowledge entry；如果 Nepha 标记 skip，则删除对应 memory entry。
- 冻结 `schemas/knowledge_entry.schema.yaml`，最小字段包括 `entry_id`、`stock_code`、`sector_tags`、`narrative_tags`、`source_pr_id`、`company_conclusions[]`、`industry_conclusions[]`、`unverified_claims[]`、`open_questions[]`、`created_at`、`expires_at`。
- 建立股票档案、行业档案、主题标签。
- Trading Agent prompt 中只注入裁剪后的历史研究摘要：同一股票最近 90 天、最多 3 条、永不注入 Perplexity 原文，始终保留未验证声明和未关闭问题。
- Brief 中展示"历史上研究过什么"。

验收标准：

- 同一股票第二天再次触发时，三位 Agent 能看到上一份 Perplexity 研究。
- Final Brief 能显示该股票历史研究摘要和未关闭问题。

### P1: 把 Research Agent 升级成 K deep 追问引擎

目标：prompt 质量从"解释价量异动"升级到"研究商业和产业关键问题"。

要做：

- 把 `research_system_v0.3.md` 中的 Gate 1-7 真正接入 prompt 生成；第一版已通过 `business_agents/research_agent/methodology_profile.py` 固化为可执行 profile。
- 生成 prompt 前检索 `research_planning_context`，自动区分已回答事实、未关闭问题、历史冲突、相似案例和过期结论。
- 每条 Research signal 输出 `research_task_plan`，把价量触发升级成 K deep 研究任务编排。
- Perplexity prompt 按问题类型分类：公司、行业、竞争、管理层、估值、监管、资本市场。
- Prompt 必须带上历史知识缺口，不重复问已经回答过的问题。
- 每条 prompt 有优先级和预期输出结构。
- 每条 research_signal 生成 `signal_fingerprint`，包含触发规则、价格方向、量能 bucket、signal_type、event_size 和可检索标签。

验收标准：

- prompt 不再只问"最近为什么涨跌"，而能问"这次变化是否改变商业模式/竞争格局/渗透率曲线"。
- 同一股票重复触发时，系统能避免重复研究已确认事实。

### P2: 升级 Chairman 和 Red Team

目标：从汇总与审计升级为裁决与反对。

要做：

- Chairman 输出 `final_verdict`、`decision_chain`、`history_context`。
- Chairman 引入历史知识和 Agent 表现上下文；复杂"相似案例检索"拆成 P2.5，不在 P2 里一次性完成。
- Red Team 检索知识库中的反例和历史失败模式。
- Red Team 输出 `strongest_objection` 和 `what_would_invalidate_this_decision`。
- Red Team 输出 `chairman_second_review`，给出 block/challenge/monitor 后 Chairman 应该如何降级或重审。

验收标准：

- Brief 里能看到 Chairman 为什么更相信某个 Agent。
- Red Team 不只是说"缺 source_url"，而能指出投资论证最脆弱的假设。

### P2.5: 建立历史相似案例检索

目标：让 Chairman 的历史类比不是凭感觉。

要做：

- 基于 `signal_fingerprint` 做第一版相似检索。
- 相似维度包括同一股票、同行业/主题、同信号类型、同触发规则、同市场叙事。
- 先返回"可参考案例"，不直接改变最终裁决。
- 第一版相似案例检索已接入知识库 tags，并进入 Chairman `history_context` 与 Red Team `similar_case_risks`。

验收标准：

- Chairman 能看到"这次 BABA 异动和过去哪些信号相似，以及相似在哪里"。
- Red Team 能攻击 Chairman 的历史类比是否成立。

### P3: 建立 Agent 成长和复盘系统

目标：让系统知道自己过去哪里准、哪里错。

要做：

- 建立 Decision Verification Log。
- 每个裁决自动进入 1/7/30/90 天复盘队列。
- 记录价格、新闻、研究结论变化，但验证结论不能只按价格涨跌判断。
- 冻结 `schemas/decision_verification.schema.yaml`，验证状态只能是 `validated / partially_validated / invalidated / inconclusive`，非 pending 状态必须有 `evidence_url`。
- 为 `long / watch / avoid / abstain` 分别定义目标函数：`long` 验证 thesis 与价格/基本面共同成立；`watch` 验证等待是否保留选择权；`avoid` 验证被避开的风险是否真实；`abstain` 验证证据不足是否成立。
- 生成 Partner Performance Log。
- Partner Performance Log 第一阶段只给 Chairman 和 Nepha 看，不反向注入三位 Agent prompt，避免历史准确率污染各自方法论。
- 每月输出投资委员会复盘报告。
- 每次 archive brief 后自动生成 `partner_performance/reviews/PARTNER-REVIEW-*.json/md`，包含 Agent 表现权重、诊断和 Red Team 反对意见有效性样本。

验收标准：

- 系统能回答"F partner Agent 过去 90 天在哪类股票上最准确"。
- 系统能回答"Chairman 最近是否过度保守"。
- 系统能回答"哪些 Red Team 反对意见后来被验证为真实风险"。

## 9. 工程原则

- 本地优先：所有核心数据和决策链保存在本机。
- 人在回路：Perplexity 由 Nepha 手动使用，系统只生成 prompt 和消费回填。
- 可追溯：每个结论必须能追到 research_signal、Perplexity 报告、Agent recommendation、Chairman 裁决和 Red Team 反对。
- 可复盘：没有验证队列的判断不算公司知识。
- 不自动交易：系统不接券商，不下单，不替 Nepha 执行交易。
- 不装懂：证据不足时必须明确 `research_more`、`watch` 或 `abstain`。
- 每天变聪明：任何高质量研究都不能只被当天消费。
- 性能反馈先给 Chairman：Agent 成长档案先用于 Chairman 权重和 Nepha 复盘，不直接喂给三位投资大佬。

## 10. 明确不做的事

为了抵御 feature creep，以下事项不进入当前系统边界：

- 不接 Bloomberg、Wind 等付费数据源。
- 不引入第 4 位投资大佬，保持三人辩论的认知负载。
- 不让 Agent 自动改写自己的方法论；方法论升级必须由 Nepha 触发并人工确认。
- 不做分钟级或实时交易决策，系统是日频投研公司，不是高频交易系统。
- 不做自动仓位管理；仓位由 Nepha 自己决定，系统只给方向、证据链、反对意见和裁决导航。
- 不绕过 Perplexity 手动质量门；Deep Research 由 Nepha 手动提交，系统只消费回填。

## 11. 目标态一句话

Worldpay77 要成为一个由 Nepha 拥有的 AI Native 投资公司：它用 K deep / K deep 体系发现真正值得研究的问题，用 Perplexity 做世界级研究，用三位投资大佬进行独立判断，用 Chairman 做有逻辑链的裁决，用 Red Team 做不妥协的反对，并把每天的研究、判断、反对和验证结果沉淀成长期记忆。

系统真正完成的标志不是"能跑出一份报告"，而是：

**明天的系统，比今天更懂这只股票、更懂这个行业、更懂三位 Agent 的强弱，也更懂自己过去错在哪里。**
