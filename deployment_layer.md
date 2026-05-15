---
document_id: deployment_layer
display_name: "1+3 Agent 系统部署层（统一硬约束）"
version: 0.1
created_at: 2026-05-13
author: Nepha
status: draft
applies_to:
  - f_partner (v0.4 → v0.5 待补丁)
  - w_partner (v0.2 → v0.3 待补丁)
  - g_partner (v0.4 → v0.5 待补丁)
not_applies_to:
  - k_deep (v0.3) - 研究上游 Agent 不持仓，不受本部署层约束
source_of_truth: 本文档抽取自F partner v0.4 / W partner v0.2 / G partner v0.4 三套已 frozen 方法论中的重合部署规则
related_files:
  - methodology_f_partner.md
  - methodology_w_partner-3.md
  - methodology_g_partner.md
  - methodology_comparison_table.md
changelog:
  - "v0.1: 首次抽取。整合三套交易 Agent 的重合部署规则；冲突点按工程主版本决策。"
---

# 1+3 Agent 系统部署层（统一硬约束）

## 为什么有这份文档

在F partner v0.4 / W partner v0.2 / G partner v0.4 三套方法论文档中，**仓位、风控、流动性、权限、市值**等部署规则高度重合（详见 `methodology_comparison_table.md` 第二部分）。如果让三份文档各自维护这些规则，**改一个数字要改三处**，必然失同步。

本文档把这些重合规则抽出为系统级单一真源（single source of truth），三套交易方法论的 v0.5 / v0.3 / v0.5 补丁会引用本文档而非重复定义。

## 本文档的权威性

本文档定义的规则是 **deployment_hard_rules 级别**，在所有交易 Agent 的 Layered Authority 中处于最高优先级——优先于任何方法论决策规则和方法论哲学。

三套交易 Agent 的 Layered Authority 仍然各自保留**自己特有的部署规则**（如G partner的三段熔断、W partner的 -6% 红线选项），具体冲突解决见本文档 Section 5。

研究上游 Agent（K deep v0.3）**不受本文档约束**——它不持仓不交易，没有部署层。

---

## 1. 账户基准

| 参数 | 数值 | 来源 |
|---|---|---|
| 账户规模 | 5 万 HKD | 三套方法论 100% 一致 |
| 目标持仓数 | 5-8 只 | W partner + G partner一致；F partner未明确，按此采用 |
| 计价货币 | HKD | 港股本币，美股按汇率折算 |

---

## 2. 仓位上限（硬规则）

| 参数 | 数值 | 来源 |
|---|---|---|
| 单票最大仓位 | **12% - 15%** | 三套 100% 一致 |
| 单行业最大仓位 | **35% - 40%** | 三套 100% 一致；超过 40% 视为行业 Beta 反转会显著拖累全组合 |
| 首次建仓比例 | **5% - 7%** | 三套 100% 一致；对应"小仓验证假设"阶段，同时覆盖港美股单边 0.3%-0.5% 摩擦成本 |
| 满仓门槛 | 仅在四阶段全 ✓ 且贝叶斯置信度 ≥ 80% 时允许 | W partner + G partner一致 |

### 数学含义
- 5-8 只持仓 × 12-15% 单票 → 理论权益仓位 60-120%
- 减去 ≥ 20% 现金底线 → 有效权益仓位上限约 80%
- 这是组合最大回撤推导的基础（见 Section 4）

---

## 3. 现金 / 流动性

### 3.1 现金底线（硬规则）

| 参数 | 数值 | 来源 |
|---|---|---|
| 组合现金 / 观察仓底线 | **≥ 20%** | 三套 100% 一致 |

### 3.2 流动性三道锁（硬规则）

进入候选池前必须全部通过：

| 锁 | 港股 | 美股 | 来源 |
|---|---|---|---|
| **入池锁**：20 日均日均成交额 | ≥ 5,000 万 HKD | ≥ 2,000 万 USD | 三套 100% 一致 |
| **退出锁**：单票持仓 / 日均成交额 | ≤ 0.5% | ≤ 0.3% | W partner + G partner一致 |
| **压力退出锁**：成交萎缩 70% 情景下退出天数 | ≤ 3 个交易日 | ≤ 2 个交易日 | W partner + G partner一致 |
| **可研究性锁**：近 12 个月主流卖方研报覆盖 | ≥ 3 份 | ≥ 3 份 | 三套 100% 一致 |

### 3.3 流动性动态校准（硬规则）

> **采用G partner v0.4 的动态校准设计作为系统主版本。**
> 工程理由：固定阈值在市场恐慌期会失效，动态校准更稳健。

| 校准类型 | 触发条件 | 动作 |
|---|---|---|
| 例行校准 | 每 3 个月 | 拉近 3 个月港美股真实日均成交额分布，重算入池下限与 0.5%/0.3% 退出比 |
| 紧急校准 | VIX > 30，或恒指波幅 > 25 且持续 5 日 | 用当前压力期实际成交萎缩幅度替代默认 70% 假设 |
| 年度深度校准 | 每年 5 月 | 用过去 12 个月两段最差流动性日做压力测试回算 |

---

## 4. 风控（硬规则）

### K deep 单票止损

| 参数 | 数值 | 来源 |
|---|---|---|
| 单票强制止损 | **-7%** | 三套 100% 一致 |
| 止损后处理 | 强制清仓，**不补仓** | 三套 100% 一致 |
| 例外 | 仅在用户明确把该标的改为长期主仓且重新批准风控豁免时才能绕过 | F partner明确，W partner/G partner默认 |

**与方法论的关系**：止损触发后清仓优先级高于任何方法论"应该加仓"或"长期持有"的判断。三套交易 Agent 在 Output Schema 中必须输出 `authority_resolution.overridden_by_deployment: true` 并在 `kill_log` 记录此次清仓违反了哪条方法论原则。

### 4.2 组合回撤熔断（采用G partner三段熔断作为系统主版本）

> **决策**：三套对组合回撤的处理差异最大（F partner无、W partner -6% 单档、G partner -8/-12/-15 三段）。
> **采用G partner的三段熔断作为系统主版本**。
> 工程理由：三段比单档更精细，能在不同回撤阶段差异化响应；而F partner"不设组合红线"在工程上必须有兜底。

| 触线阶段 | 阈值 | 强制动作 |
|---|---|---|
| 🟡 黄线 | 组合回撤 ≥ 8% | 停止加仓 + 对所有持仓重做贝叶斯后验更新 |
| 🟠 橙线 | 组合回撤 ≥ 12% | 强制降至 60% 仓位（现金 ≥ 40%）+ 优先砍置信度最低持仓 |
| 🔴 红线 | 组合回撤 ≥ 15% | 强制降至 30% 仓位 + 暂停新建仓 2 周 + 输出整体复盘报告 |

**保留W partner v0.2 的 -6% 复盘红线作为可选预警层**：
- 当组合回撤达到 -6% 时，发出"接近熔断"警报，但不强制动作
- 此时 PM 可主动复核杀跌类型 / 现金底线 / 持仓逻辑
- 这是黄线 -8% 之前的预热

### 4.3 交易冷却期

| 参数 | 数值 | 来源 |
|---|---|---|
| 单标的买卖后冷却期 | **48 小时** | 三套 100% 一致 |
| 含义 | Agent 不得对同一标的发新建议，防止过度交易 | |

### 4.4 年换手率上限

| 参数 | 数值 | 来源 |
|---|---|---|
| 年换手率上限 | **150%** | F partner v0.4 明确；W partner/G partner未明确，按此采用 |

---

## 5. 权限边界（硬规则，最严格）

| 权限 | 状态 | 三套一致性 |
|---|---|---|
| 融资 / 杠杆 | ❌ 不允许 | 100% 一致 |
| 买 Put | ❌ 不允许 | 100% 一致 |
| 做空 | ❌ 不允许 | 100% 一致 |
| 做空对冲 | ❌ 不允许 | 100% 一致 |
| 衍生品（期权/期货/CFD 等）| ❌ 不允许 | W partner + G partner明确禁止；F partner隐含禁止 |
| 双重上市标的 | ✅ 允许，但只交易流动性更好的一边 | 三套一致 |

**Agent 工程含义**：
- 任何 Agent 输出 `recommendation.direction: short` 或 `position_size_pct < 0` 都视为违规
- 任何 Agent 输出包含 put/option/derivative 字段都视为违规
- 违规建议必须被系统层 reject，不允许进入 Chairman 汇总

---

## 6. 市值门槛（硬规则）

| 市场 | 市值下限 | 来源 |
|---|---|---|
| 港股 | ≥ 50 亿 HKD | 三套 100% 一致 |
| 美股 | ≥ 10 亿 USD | 三套 100% 一致 |
| A 股 | 不交易 | 仅作研究案例参考（详见 A 股案例处理规则） |
| Crypto | 不交易 | 仅 K deep可研究，不进交易候选池 |

---

## 7. A 股案例处理规则（硬规则）

> W partner v0.2 和G partner v0.4 都明确规定 A 股案例处理。本部署层统一为系统规则。

- **原则**：原始材料中的 A 股案例（茅台 / 平安 / 牧原股份 / 阿里 / 腾讯 等）仅作方法论学习参考，**不进入候选池**
- **港美股映射**：
  - "中国平安" → 仅交易 H 股 `2318.HK`，不交易 A 股 `601318.SH`
  - "阿里巴巴" → 可交易 `BABA`（NYSE）或 `9988.HK`，按流动性选择
  - "腾讯" → 仅 `0700.HK`
  - "茅台" / "牧原股份" → **A 股案例学习用，不交易**
- **引用 A 股案例时的标注义务**：当 Agent 在 `thesis` 字段引用 A 股历史案例时，必须显式标注 `参考 A 股案例 <ticker>，不构成交易建议`

---

## 8. 安全边际门槛（部分抽取）

### 8.1 通用四重门槛（W partner + G partner一致，采用为系统主版本）

| 门槛 | 阈值 | 注释 |
|---|---|---|
| FCF / EV 港股 | ≥ 5% | |
| FCF / EV 美股成长股 | ≥ 4% | |
| PE 或 PS 近 5 年自身分位 | ≤ 40 分位 | 周期股用 PB，且 ≤ 30 分位 |
| 未来 2 年隐含年化 IRR | ≥ 15% | 可用 DCF 或 EPS × 目标 PE 反推 |
| 贝叶斯后验置信度（建仓）| ≥ 70% | |
| 贝叶斯后验置信度（满仓）| ≥ 80% | |

**F partner v0.4 的特殊处理**：F partner不使用四重安全边际框架，它用 `odds_score` / `probability_score` / 关注度购买度错配代替。F partner Agent 的输出可以**不填四重安全边际字段**，但必须填 `odds_score / probability_score / dislocation_score`。Chairman 汇总时需把这两套框架做映射（详见明日 Chairman 设计）。

### 8.2 FCF 负值成长股替代门槛（不抽取，保留各方法论自己版本）

> **决策**：W partner和G partner对 SaaS / 生物科技的替代门槛细节不同（rNPV/EV：1.0 vs 1.5）。这是**真实的方法论 DNA 差异**，不是抄重的部署规则。
> **本部署层不抽取**，保留各方法论自己版本。

引用：
- W partner的 SaaS / 生物科技替代门槛见 `methodology_w_partner-3.md` Gate 7 `negative_fcf_alternative_thresholds`
- G partner的 SaaS / 平台型 / 生物科技替代门槛见 `methodology_g_partner.md` Section 2 `成长股例外规则`

---

## 9. 持仓周期（部分抽取）

### 9.1 通用约束

| 参数 | 数值 | 来源 |
|---|---|---|
| 主要持仓周期 | 周级和月级 | 三套都接受这个区间 |
| 日内 / 隔夜交易 | 仅作风控观察，不作为主动交易目标 | F partner明确 |
| 季度级以上持仓 | 不是默认状态，必须重证三率/安全边际 | W partner明确 |

### 9.2 不抽取部分（属于方法论 DNA）

- F partner的"时间不值钱"哲学
- G partner的"5-10 年目标持有期 vs 时间盒 4 周/3 月/6 月"两层架构

这些保留在各方法论 Layered Authority 的 `methodology_philosophy` 层。

---

## 10. Output Schema 共享字段（v0.5 补丁要点）

三套交易 Agent v0.5 / v0.3 / v0.5 补丁后，Output Schema 必须包含以下 **3 个共享字段块**：

### 10.1 `deployment_compliance`（新增）

```yaml
deployment_compliance:
  deployment_layer_version: 0.1
  hard_rules_passed:
    position_size_pct: true | false         # 单票仓位是否合规
    industry_exposure_pct: true | false     # 单行业仓位是否合规
    cash_floor_pct: true | false            # 现金底线是否合规
    liquidity_three_locks: true | false     # 流动性三道锁是否全过
    market_cap_minimum: true | false        # 市值门槛是否过
    forbidden_actions_check: true | false   # 是否绕过权限边界
    cooldown_check: true | false            # 是否在冷却期内
  any_failure_must_abstain: true            # 任一硬规则未过必须 abstain
```

### 10.2 `authority_resolution`（已有，与 Layered Authority 联动）

```yaml
authority_resolution:
  overridden_by_deployment: true | false    # 本建议是否被部署层规则覆盖
  overridden_principle:                     # 覆盖了哪条方法论原则
  philosophy_deferred: true | false         # 方法论哲学是否被让位
  kill_log: []                              # 部署层强制干预的记录
```

### 10.3 `upstream_research_signals[]`（新增 - 与 K deep对接）

```yaml
upstream_research_signals:
  - research_signal_id:                     # 引用 K deep的信号 ID
    signal_summary:
    my_methodology_verdict: accepted | rejected | partial
    verdict_reason:
    pull_request_id:                        # 若是被动响应
    used_perplexity_results: true | false   # 是否使用了 Nepha 手动回填的 Perplexity 结果
```

---

## 11. 与方法论的冲突解决（Layered Authority 顶层规则）

三套交易 Agent 的 Layered Authority 第一层 `deployment_hard_rules` 现在统一引用本文档：

```yaml
authority_priority:
  - level: deployment_hard_rules
    source: deployment_layer.md v0.1
    items: 见本文档 Section 1-7
  - level: methodology_decision_rules
    items: 各方法论自己的 Gate 1-N
  - level: methodology_philosophy
    items: 各方法论自己的哲学锚点
```

### 通用冲突解决规则（沿用既有 R1-R4）

- **R1**：deployment_hard_rules 与 methodology_decision_rules 冲突时，前者优先。Agent 必须在 `recommendation.authority_resolution.overridden_by_deployment: true` 标注
- **R2**：methodology_decision_rules 与 methodology_philosophy 冲突时，前者优先。Agent 必须标注 `philosophy_deferred: true`
- **R3**：单票 -7% 止损触发时，清仓优先，必须在 `kill_log` 记录此次清仓违反了哪条方法论原则
- **R4**：Agent 若发现自身建议同时违反 deployment_hard_rules，必须直接 `abstain`，不允许发出建议

### 各方法论保留的特殊规则

| Agent | 保留的特殊规则 | 简述 |
|---|---|---|
| F partner v0.5 | 无（v0.4 的 R1-R4 全部通用化）| 引用本文档 Section 11 |
| W partner v0.3 | R5 | 核心问题 > 3 个 → `abstain`（来自原话）|
| G partner v0.5 | R5 / R6 / R7 | R5 时间盒 vs 长期持有 / R6 心态好 vs 强制止损 + false_stop_loss_review / R7 95% vs 70% 双门槛 |

---

## 12. 本部署层 v0.1 的未解问题

以下问题不影响本文档生效，但需要后续校准：

- [ ] **黄/橙/红熔断在牛市的修正**：G partner设计的 -8/-12/-15 是基于年回撤容忍 15%。在强势牛市中，回撤可能短期触发但非系统性。是否需要"3 个交易日内自动恢复"机制？
- [ ] **48 小时冷却期的例外**：当 -7% 止损刚触发但 24 小时内出现 thesis 反转的硬证据，是否允许冷却期内重新建仓？默认禁止
- [ ] **流动性紧急校准的 VIX 阈值**：30 这个数字是G partner v0.4 工程推断，是否需要根据中美市场特性差异化（如港股用恒指波幅、美股用 VIX）？
- [ ] **A 股案例的"案例学习用"标注是否够**：当某个 A 股标的（如牧原）的研究价值很高时，是否允许通过 A+H 联动间接持有？默认禁止
- [ ] **年换手率 150% 的实操**：仅F partner v0.4 明确，是否真适合W partner/G partner？W partner原本就限制频繁交易，可能更严
- [ ] **DEC-018 / 账户规模变化时的 reduce 档位重算**：账户从 5 万 HKD 扩大后，DEC-009 的 8% / 5% reduce 档位是否需要重算？
  - 小额（≤ 50 万 HKD）：按比例保持 8% / 5% 合理
  - 中额（50-500 万 HKD）：可能需调整为 10% / 6%
  - 大额（> 500 万 HKD）：需重新设计 reduce 额层
  - 实际门阈需根据账户增长路径和流动性限制时才能决定

---

## 13. 三套交易 Agent v0.5 补丁清单（明日推进用）

明日给 Codex 的 v0.5 / v0.3 / v0.5 补丁指令需要让三套交易 Agent 做以下事：

### 共同补丁（三套都做）

1. **frontmatter 新增**：`deployment_layer_ref: deployment_layer.md v0.1`
2. **Layered Authority 改写**：第一层 deployment_hard_rules 不再列具体数值，改为引用 `deployment_layer.md`，仅在本方法论有特殊补充时显式标注（如G partner的三段熔断已是部署层主版本，不再单独列）
3. **Output Schema 新增三个字段块**：`deployment_compliance` / `authority_resolution`（增强）/ `upstream_research_signals[]`
4. **Layered Authority 新增 R8**：本 Agent 不自行调用 Perplexity，所有研究请求通过 pull_request 提交给 K deep

### F partner特殊补丁

- 在 Output Schema 中保留 `odds_score` / `probability_score` / `dislocation_score`，不强制填四重安全边际字段
- 在 Layered Authority 中说明"本 Agent 不使用通用四重安全边际框架，使用自己的赔率/概率/错配框架"

### W partner特殊补丁

- 保留 R5（核心问题 > 3 个 → abstain）
- 保留 FCF 负值替代门槛中的 rNPV/EV ≥ 1.0（与G partner的 1.5 不同，是方法论 DNA 差异）

### G partner特殊补丁

- 保留 R5 / R6 / R7
- 保留 5-10 年持有期 vs 4 周/3 月/6 月时间盒的双层架构
- 保留 95% 胜率 vs 70% 贝叶斯的双门槛
- 三段熔断从"G partner特有"改为"部署层主版本"，文档中只需说明"本方法论沿用 deployment_layer.md Section 4.2 三段熔断"

---

## 14. 修订历史

- v0.1 (2026-05-13)：首次抽取。基于F partner v0.4 / W partner v0.2 / G partner v0.4。
- v0.1.1 (2026-05-13)：小补丁。Section 12 加 DEC-018 完整 Open Question（账户规模变化时的 reduce 档位重算）。

## 15. 致谢

本部署层抽取建议最初来自 **Codex 在G partner v0.4 revision_summary 中的工程观察**："这些重叠是合理的，因为它们更像'同一账户、同一 PM、同一小资金规模'的部署层，而不是方法论 DNA。建议抽出独立的 `deployment_layer.md`，每套方法论文档只引用它。"

这是 Codex 在整个 4 套方法论提取过程中给出的最有工程价值的洞察之一。
