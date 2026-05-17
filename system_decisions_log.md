# 系统级决策日志

> 记录在整合阶段做出的、影响多个 Agent 的工程决策。每条决策有明确触发上下文、最终决定、影响范围。

---

## DEC-001：f_partner_specific_framework 与四重安全边际的 Chairman 映射

- **触发**：F partner v0.5 验收，Codex 反向追问 Q1
- **决定**：Chairman **不做语义映射，分两路独立汇总**
- **理由**：
  - F partner odds_score 测的是"赔率"
  - W partner/G partner四重门槛测的是"绝对估值合理性"
  - 两者数学上不等价，强行映射会产生误导
- **Chairman 输出格式**：
  - 赔率维度：F partner odds_score / W partner odds_score / G partner（无独立 odds_score，隐含在 margin_of_safety）
  - 绝对估值维度：F partner豁免 / W partner 4 门槛 / G partner 4 门槛
  - 不允许做加权平均或映射等价
- **影响范围**：Chairman Agent 设计（阶段 3.3）
- **决策时间**：2026-05-13 10:15

---

## DEC-002：R8 pull_request 不在交易 Agent 端节流

- **触发**：F partner v0.5 验收，Codex 反向追问 Q2
- **决定**：交易 Agent 端**不加节流**，全部由 K deep的 system_hard_rules 兜底
- **理由**：
  - K deep已有 `max_prompts_per_signal: 5` + `max_prompts_per_daily_brief: 30` 形成天然约束
  - Agent 端再加节流是过度设计
  - 如果某 Agent pull 过多，由 Nepha 在 K deep 端降级该 Agent 的优先级
- **影响范围**：三套交易 Agent v0.5 / v0.3 / v0.5 + K deep v0.3（无改动需求，已经覆盖）
- **决策时间**：2026-05-13 10:15

---

## DEC-003：abstain 状态下 thesis 必须填 + 新增 abstain_reason 字段

- **触发**：F partner v0.5 验收，Codex 反向追问 Q3
- **决定**：
  1. `direction: abstain` 时 thesis 字段必须填（解释为什么决定不发建议）
  2. **所有三套交易 Agent 的 deployment_compliance 字段块新增 `abstain_reason` 子字段**
  3. abstain_reason 是机器可读枚举，便于后期归类统计
- **abstain_reason 枚举值**（系统级统一）：
  ```yaml
  abstain_reason:
    # 部署层硬约束类
    - liquidity_lock_failed         # 流动性三道锁未过
    - market_cap_below_minimum      # 市值未达门槛
    - position_size_exceeds_limit   # 单票/单行业仓位将超限
    - cash_floor_violated           # 触及 20% 现金底线
    - cooldown_active               # 48 小时冷却期内
    - forbidden_action_required     # 建议涉及融资/做空/Put/对冲/衍生品
    
    # 方法论决策类
    - circle_status_outsider        # F partner：外行且非顺势短线
    - kill_type_logic_kill          # F partner：判定为杀逻辑
    - core_questions_exceed_3       # W partner：核心问题 > 3 个（R5）
    - win_rate_below_95             # G partner：胜率 < 95%
    - sharp_variables_exceed_2      # G partner：sharp 变量 > 2 个
    
    # 上游信号类
    - upstream_signal_evidence_unverified  # K deep 信号有 P0 prompt 未回填
    - upstream_signal_not_applicable        # 上游信号不适合本方法论
    
    # 通用类
    - insufficient_data              # 数据不足
    - methodology_specific_other     # 方法论特有原因，详见 thesis
  ```
- **影响范围**：
  - F partner v0.5 → 需在 v0.5.1 微补丁补 abstain_reason
  - W partner v0.3 → 在本轮补丁直接加（明日验收时检查）
  - G partner v0.5 → 在本轮补丁直接加（明日验收时检查）
- **决策时间**：2026-05-13 10:15

---

## DEC-004：evidence_unverified_inherited 的双重处理

- **触发**：F partner v0.5 验收，Codex 反向追问 Q4
- **决定**：固定扣分 + Red Team 标记**并存**
- **具体规则**：
  ```yaml
  when_evidence_unverified_inherited_is_true:
    - confidence_ceiling: 70   # confidence 上限不超过 70，与 K deep v0.3 的 P1 prompt skipped 规则对齐
    - red_team_priority: high  # 同时打 high 优先级 Red Team 标记
    - chairman_weight_discount: 0.7  # Chairman 汇总时该建议的投票权重 × 0.7
  ```
- **理由**：
  - 单独依赖标记，Chairman 无法量化加权
  - 单独依赖扣分，丢失 Red Team 介入钩子
  - 双重处理保证既有量化基础（扣分），又保留人工介入空间（标记）
- **影响范围**：
  - 三套交易 Agent 的 upstream_research_signals 字段处理逻辑
  - Chairman Agent 投票权重计算
  - Red Team Agent 优先级队列
- **决策时间**：2026-05-13 10:15

---

## DEC-005：F partner v0.5 待统一议程（v0.5.1 微补丁）

记录F partner v0.5 验收时发现但按"最小补丁"原则未改的 3 项遗留问题。**在 3 套交易 Agent 全部 v0.5 frozen 后，做一次跨 Agent 统一微补丁**。

1. **direction 枚举统一为 `[long, short, watch, avoid, abstain]`**
   - F partner：缺 abstain，必须加
   - W partner：缺 short（如有 short 需求）
   - G partner：缺 short
   - 统一后各 Agent 可标注自己实际可输出的子集
2. **删除 v0.4 Output Schema 中的 `deployment_controls` 字段**（F partner特有）
   - 已被 deployment_layer.md 替代，留着违反"单一真源"原则
3. **Section 4 Position Sizing & Risk Rules 改为重定向说明**（F partner/W partner/G partner共同）
   - 部署层规则全部由 deployment_layer.md 管
   - 仅保留方法论 DNA 部分（加仓/减仓/清仓的方法论触发条件）
- **决策时间**：2026-05-13 10:15
- **执行时机**：3 套交易 Agent 全部 v0.5 frozen 后，进入 Chairman 设计前

---

## DEC-006：W partner mapped_to_three_models.subjective_cognition_gap 的映射规则

- **触发**：W partner v0.3 验收，Codex 反向追问 Q3
- **背景**：K deep不输出"主观认知差"判断，但W partner需要把上游信号映射到三型之一
- **决定**：使用 K deep 的 `bayesian_update.posterior_minus_market_prior` 作为映射依据
  ```yaml
  mapping_rule:
    if abs(posterior_minus_market_prior) > 20%:
      subjective_cognition_gap: true
    else:
      subjective_cognition_gap: false
  ```
- **理由**：
  - posterior_minus_market_prior 是 K deep 对"市场认知差"的量化表达
  - W partner的主观认知差概念本质上就是"我看到的概率 vs 市场看到的概率"
  - 用这个数值作为映射 trigger 既保留了W partner方法论 DNA，又利用了上游已有信息
- **阈值**：20% 是工程推断，需要前 3 个月真实数据校准
- **影响范围**：W partner v0.3 / v0.3.1 微补丁
- **决策时间**：2026-05-13 10:24

---

## DEC-007：W partner collaborative_validation 中 K deep 计为 +1 validator

- **触发**：W partner v0.3 验收，Codex 反向追问 Q1
- **决定**：
  1. K deep信号计为 collaborative_validation 的 1 个独立验证源
  2. 最低门槛保持 v0.2 的 ≥ 2 个，不提高到 3 个
  3. **例外**：当 K deep 信号的 `evidence_unverified_inherited: true` 时，该验证源不计入 independent_validators_count
- **理由**：
  - K deep 是经过 Nepha 手动 Perplexity 验证的高质量来源
  - 5 万 HKD 小账户、5-8 只持仓场景下，3 个验证源过严
  - evidence_unverified 状态下不计入是为了避免污染
- **影响范围**：W partner v0.3 / v0.3.1 微补丁 + Chairman Agent 设计
- **决策时间**：2026-05-13 10:24

---

## DEC-008：R5/R6/R7 字段在 Chairman 汇总中只做审计，不参与横向投票

- **触发**：G partner v0.5 验收，Codex 反向追问 Q5
- **决定**：G partner特有的 r5_time_box_resolution / r6_false_stop_loss_review_triggered / r7_dual_gate_status 字段在 Chairman 设计中 **只做审计，不参与横向投票权重**
- **设计考量**：
  - 这些字段是"G partner Agent 内部冲突解决的过程记录"，不是"对标的的判断"
  - 让这些字段参与投票会污染 Chairman 的横向比较
- **例外**：Red Team 必须读这些字段，它们是评估G partner Agent 是否自洽的关键数据
- **影响范围**：Chairman / Red Team Agent 设计
- **决策时间**：2026-05-13 10:30

---

## DEC-009：r5_time_box_resolution.reduce 比例按置信度动态决定

- **触发**：G partner v0.5 验收，Codex 反向追问 Q1
- **决定**：不固定减半，按 posterior_confidence_at_review 动态决定
  ```yaml
  reduce_action_rules:
    posterior_confidence_at_review 60-70%: reduce to 8%   # 接近初始建仓比例
    posterior_confidence_at_review 50-60%: reduce to 5%   # 试错仓水平
    posterior_confidence_at_review < 50%: exit            # 退出不减仓
  ```
- **理由**：
  - 5 万 HKD 小账户下固定减半会出现 7.5% → 3.75% 碎片仓位
  - 不符合 deployment_layer 5-7% 首次建仓的颞粒度
  - 按置信度分档更符合"贝叶斯全程驱动"哲学
- **影响范围**：G partner v0.5 / v0.5.1 微补丁
- **决策时间**：2026-05-13 10:30

---

## DEC-010：mapped_to_three_powers 使用 discontinuity_assessment.type 做映射

- **触发**：G partner v0.5 验收，Codex 反向追问 Q2
- **背景**：K deep输出 discontinuity_assessment.type 枚举，但不输出护城河/进化力/熵减力判断
- **决定**：建立如下映射规则（由G partner Agent 在接收上游信号后应用）
  ```yaml
  mapping_rules:
    discontinuity_assessment.type == business_model:
      mapped_to_three_powers.evolution_power_change: true
    discontinuity_assessment.type == market_structure:
      mapped_to_three_powers.evolution_power_change: true
    discontinuity_assessment.type == cost_efficiency:
      mapped_to_three_powers.moat_change: true
    discontinuity_assessment.type == policy:
      mapped_to_three_powers.moat_change: true   # 政策会改变护城河
    discontinuity_assessment.type == penetration:
      # 部分映射，需 Agent 自行判断
      requires_agent_judgment: true
    discontinuity_assessment.type == supply_demand:
      requires_agent_judgment: true
    discontinuity_assessment.type == other:
      requires_agent_judgment: true
  entropy_reduction_change:
    # 熵减力判断几乎不可能从上游信号机械映射获得
    # 需G partner Agent 独立评估管理层类例/资源集中度/组织活力
    typically_set_by_agent_only: true
  ```
- **影响范围**：G partner v0.5 / v0.5.1 微补丁
- **决策时间**：2026-05-13 10:30

---

## DEC-011：dual_gate_consistency 机器判定规则

- **触发**：G partner v0.5 验收，Codex 反向追问 Q3
- **背景**：R7 要求 95% 胜率门槛与 70% 贝叶斯门槛数学独立，但未定义"独立"的机器判定标准
- **决定**：4 种组合明确对应 4 种决策
  ```yaml
  dual_gate_consistency_judgment:
    case_1:
      condition: win_rate_95_passed AND bayesian_70_passed
      consistency: aligned
      action: 正常建仓
    case_2:
      condition: win_rate_95_passed AND NOT bayesian_70_passed
      consistency: independent_not_yet_ready   # 胜率高但贝叶斯证据未到位
      action: watch_or_pull_request           # 进观察池或发 pull_request
      note: 这是独立成立但暂不建仓，不是异常
    case_3:
      condition: NOT win_rate_95_passed AND bayesian_70_passed
      consistency: anomaly_review_required   # 胜率未达但贝叶斯高 - 可能是 Agent 计算错误
      action: abstain + red_team_priority_high
      note: 这个组合有内部矛盾，不允许建仓
    case_4:
      condition: NOT win_rate_95_passed AND NOT bayesian_70_passed
      consistency: both_failed
      action: avoid
  ```
- **影响范围**：G partner v0.5 / v0.5.1 微补丁 + Red Team Agent 设计（case_3 是 Red Team 高优先级输入）
- **决策时间**：2026-05-13 10:30

---

## DEC-012（否决提案）：不推广 bayesian_update / time_box / red_team 到F partner/W partner

- **触发**：G partner v0.4 Schema 字段分类表中，Codex 建议"推广这三个字段到其他方法论 v0.5"
- **决定**：不推广
- **理由**：
  - W partner的 collaborative_validation 等价于 red_team 的某些功能（更精英协同导向）
  - F partner的 confidence 单值是其方法论 DNA，强加 bayesian_update 子字段会扭曲
  - 时间盒是G partner R5 的独特设计，硬塞到W partner/F partner会破坏它们各自的 Layered Authority 一致性
  - **保持差异比统一更有价值**——4 Agent 辩论张力的来源
- **影响范围**：F partner v0.5.1 / W partner v0.3.1 不需加这三个字段
- **决策时间**：2026-05-13 10:30

---

## DEC-013：F partner circle_status_outsider 分层处理

- **触发**：F partner v0.5.1 反向追问 Q1
- **决定**：外行状态下不是统一 abstain，三档处理：
  ```yaml
  outsider_handling:
    case_1_outsider_with_clear_trend_signal:
      action: long
      position_size: < 主仓水平
      rationale: F partner原文"外行只允许顺势中短线、仓位应低于主仓"
    case_2_outsider_no_trend_signal:
      action: abstain
      abstain_reason: circle_status_outsider
      rationale: 看不懂图形与逻辑，不懂就放弃
    case_3_outsider_with_logic_break:
      action: avoid
      rationale: 看清了反向证据，不是 abstain 是 avoid
  ```
- **影响范围**：Chairman 在处理 abstain_reason: circle_status_outsider 时需要同时检查是否该走 case_3 路径
- **决策时间**：2026-05-13 11:08

---

## DEC-014：F partner kill_type_logic_kill 按 confidence 分流

- **触发**：F partner v0.5.1 反向追问 Q2
- **决定**：使用 v0.4 已定义的 kill_type_heuristic.logic_kill.confidence 作为分流阈值
  ```yaml
  logic_kill_routing:
    if kill_type_heuristic.logic_kill.confidence >= 0.65:
      action: avoid
      rationale: 证据充分判定为杀逻辑，明确反对
    elif kill_type_heuristic.logic_kill.confidence in [0.50, 0.65):
      action: abstain
      abstain_reason: kill_type_logic_kill
      rationale: 有杀逻辑嫂疑但证据不足，挑彻追问安全为上
    else:
      not_logic_kill: true
      # 走 valuation_kill / earnings_kill / mixed 其他分支
  ```
- **阈值来源**：0.65 是 v0.4 kill_type_heuristic 已定义的 logic_kill 默认 confidence
- **影响范围**：F partner Agent 运行逻辑 + Chairman 处理 abstain_reason: kill_type_logic_kill 时的预期
- **决策时间**：2026-05-13 11:08

---

## DEC-015：W partner posterior_minus_market_prior 阈值第一版不分层

- **触发**：W partner v0.3.1 反向追问 Q1
- **决定**：第一版统一 20% 阈值，不按行业/市值分层
- **理由**：
  - 现在分层是"假精确"，基于零样本数据拍脑袋
  - 统一 20% 跑 3 个月，记录每次触发的真实市值/行业分布
  - 数据驱动决定要不要分层
- **后续动作**：加入W partner v0.3.1 Open Questions："M4 （3 个月后）评估 20% 阈值在大/中/小市值、消费/医药/科技 不同下的触发分布。"
- **影响范围**：W partner v0.3.1 不动代码，仅加一条 Open Question
- **决策时间**：2026-05-13 11:08

---

## DEC-016：W partner nepha_manual_validation 必须有证据链才计入

- **触发**：W partner v0.3.1 反向追问 Q2
- **决定**：Nepha 手动验证只在留下证据链接时计入 collaborative_validation
  ```yaml
  nepha_manual_validation_entries:
    - validation_at: <timestamp>
      evidence_url:                    # 必填，无则不计入
      evidence_summary:
      counts_as_validator: true | false  # 仅在 evidence_url 非空时为 true
  ```
- **理由**：避免"我验证过了"的自欺，强制可审计
- **实施方式**：需W partner v0.3.1 文档加一个子字段。由 Computer 直接小补丁，不走 Codex
- **影响范围**：W partner v0.3.1 + Chairman validators 计数逻辑
- **决策时间**：2026-05-13 11:08

---

## DEC-017：G partner DEC-011 case_2 按证据类型自动路由

- **触发**：G partner v0.5.1 反向追问 Q1
- **决定**：case_2（win_rate 过、bayesian 未过）的 watch vs pull_request 选择由证据缺口类型决定
  ```yaml
  case_2_routing:
    decision_input:
      bayesian_gap_type:
        - perplexity_obtainable     # 可外包类：行业数据、竞品对比、专家访谈
        - time_dependent            # 不能外包类：下次财报、临床数据
        - quality_assessment        # 需 Agent 独立评估：管理层判断、护城河演化
    
    if bayesian_gap_type == perplexity_obtainable:
      action: 发起 pull_request 给 K deep
    else:
      action: watch（进观察池）
  ```
- **影响范围**：G partner Agent 运行逻辑（不需改文档 schema，是代码实现级逻辑）+ Chairman 预期 case_2 不同路径
- **决策时间**：2026-05-13 11:08

---

## DEC-018：deployment_layer 加 Open Question：账户规模变化时的 reduce 档位重算

- **触发**：G partner v0.5.1 反向追问 Q2
- **决定**：v0.5.1 不动，但在 deployment_layer.md 加一条 Open Question
- **待加 Open Question 内容**：
  > 账户规模从 5 万 HKD 扩大后，DEC-009 的 8% / 5% reduce 档位是否需要重算？
  > - 小幼额（≤ 50 万 HKD）：按比例保持 8% / 5% 合理
  > - 中额（50-500 万 HKD）：可能需调整为 10% / 6%
  > - 大额（> 500 万 HKD）：需重新设计 reduce 额层
  > 实际门阈需根据账户增长路径和流动性限制时才能决定
- **实施方式**：由 Computer 直接更新 deployment_layer.md 加一条 Open Question，不走 Codex
- **影响范围**：deployment_layer.md
- **决策时间**：2026-05-13 11:08

---

## DEC-019：从投委会否决器改为机会筛选与人工开枪系统

- **触发**：`worldpay77_agent_improvement_notes.md` 指出当前 Chairman + Red Team 流程过度偏向审计、否决和 `wait/research_more/reject`。
- **决定**：Chairman 不再把最终输出压成 `act / wait / reject / research_more`，而是输出 human-in-the-loop 机会状态：
  ```yaml
  final_verdict:
    - discard
    - watch
    - research_priority
    - trial_candidate
    - conviction_candidate
    - human_override_required
  ```
- **Opportunity Screener**：在每只股票 summary 中新增 `opportunity_screener`，拆分 `business_quality_score` 与 `investment_attractiveness_score`，并记录预期差、估值、催化、风险压力、持仓/叙事位置、非共识 thesis、上下行路径和 kill conditions。
- **Red Team 改造**：Red Team 不只输出阻断/挑战，还必须输出 `fatal_flaw`、`risk_budget`、`main_risks`、`kill_conditions`，把风险转成行动边界。
- **学习层**：decision case 和 verification case 保留 `opportunity_screener` 与 `human_decision_checklist`，后续 outcome review 可回测 screener 分数和机会类型。
- **影响范围**：Chairman brief、Red Team audit、decision learning、README、report template。
- **决策时间**：2026-05-17

---

## 决策应用追踪

| Agent | DEC-001 → DEC-012 状态 | DEC-013 | DEC-014 | DEC-015 | DEC-016 | DEC-017 | DEC-018 | DEC-019 |
|---|---|---|---|---|---|---|---|---|
| F partner v0.5.1 | frozen | Agent 运行时逻辑 | Agent 运行时逻辑 | n/a | n/a | n/a | n/a | 提供输入 |
| W partner v0.3.1 | frozen | n/a | n/a | 加 Open Q | 本轮小补丁 | n/a | n/a | 提供输入 |
| G partner v0.5.1 | frozen | n/a | n/a | n/a | n/a | Agent 运行时逻辑 | n/a | 提供输入 |
| deployment_layer v0.1 | frozen | n/a | n/a | n/a | n/a | n/a | 本轮小补丁 | n/a |
| K deep v0.3 | 字段源头 | n/a | n/a | n/a | n/a | n/a | n/a | Screener 输入 |
| Chairman | DEC-001/004/007/008 实施主体 | 需处理 | 需处理 | n/a | 需处理 | 需处理 | n/a | 已实施 |
| Red Team | DEC-004/011 实施主体 | n/a | n/a | n/a | n/a | n/a | n/a | 已实施 |

## 跨 Agent 微补丁清单（v0.5.1 / v0.3.1 / v0.5.1）

在 3 套交易 Agent 全部 v0.5 frozen 后，做一次统一微补丁。涉及：

| 决策 | F partner v0.5.1 | W partner v0.3.1 | G partner v0.5.1 |
|---|---|---|---|
| DEC-003 abstain_reason | 加 | 加 | 加 |
| DEC-004 evidence_unverified 双重处理 | 加 | 加 | 加 |
| DEC-005a direction 枚举统一 | 加 abstain | 加 short？ | 加 short？ |
| DEC-005b 删除 deployment_controls | 删 | 删 | 删 |
| DEC-005c Section 4 改重定向 | 改 | 改 | 改 |
| DEC-006 三型映射规则 | n/a | 加 | n/a |
| DEC-007 +1 validator 规则 | n/a | 加 | n/a |
| DEC-009 reduce 比例动态规则 | n/a | n/a | 加 |
| DEC-010 三力映射规则 | n/a | n/a | 加 |
| DEC-011 dual_gate 机器判定 | n/a | n/a | 加 |
