# worldpay77 系统运行流程图

本文按当前代码描述系统如何运行、信息如何流转，以及 LLM 在哪里参与。当前阶段是试运行版：不自动交易，不自动调用 Perplexity，不输出 `long`，交易 Agent 只能输出 `watch / avoid / abstain`。

## 1. 总运行流程

```mermaid
flowchart TD
    User["Nepha / Web UI / CLI"] --> Entry{"运行入口"}

    Entry -->|"主页：运行早间/晚间报告"| WebRun["/api/run-stream"]
    Entry -->|"CLI"| CliRun["uv run orchestrator run"]
    Entry -->|"深度研究：回填后重跑"| DeepRun["/api/deep-research/rerun-stream"]

    WebRun --> Orchestrator["Orchestrator\n创建 run_id\n写入 data/orchestrator/runs.db"]
    CliRun --> Orchestrator

    Orchestrator --> Clean["清理同日期旧输入\nresearch_signals / pull_requests / recommendations"]
    Clean --> Research["Research Agent 4.1\n公开价量扫描"]

    StockPool["data/stock_pool/master_pool.yaml\nHK/US main 股池"] --> Research
    MarketData["公开价量数据\nYahoo Finance public chart endpoint"] --> Research

    Research -->|"触发价量规则"| Signals["data/research_signals/\nRS-YYYYMMDD-TICKER.yaml"]
    Research -->|"需要人工解释原因"| Prompts["data/pull_requests/\nPR-YYYYMMDD-TICKER.yaml"]
    Research -->|"无触发"| ResearchSummary["data/research_runs/\nRESEARCH-*.yaml"]

    Signals --> TradingParallel["三位交易 Agent 并行\n冯柳 / 万木 / 李国飞"]
    Prompts --> PerplexityUI["深度研究页\n人工复制 prompt 到 Perplexity"]
    PerplexityUI --> Fill["保存回填 / 标记跳过"]
    Fill --> Results["data/perplexity_results/\nPR-*_filled.yaml 或 PR-*_skipped.yaml"]
    Results --> SyncSignal["同步 research_signal 的\nfilled / skipped / pending 状态"]
    SyncSignal --> Signals

    Results --> TradingParallel
    TradingParallel --> Recs["data/recommendations/YYYYMMDD/\nfengliu / wanmu / liguofei/*.yaml"]

    Recs --> Chairman["Chairman\n共识、分歧、升级队列、报告摘要"]
    Signals --> Chairman
    Chairman --> Brief["data/briefs/YYYYMMDD/\nBRIEF-YYYYMMDD-AM/PM.md + .json"]

    Brief --> RedTeam["Red Team\n规则审计 + 方法论挑刺"]
    Recs --> RedTeam
    Signals --> RedTeam
    RedTeam --> Audit["data/red_team_audits/YYYYMMDD/\nAUDIT-YYYYMMDD-AM/PM.md + .json"]

    Audit --> Notify["本地通知/运行完成记录"]
    Brief --> History["运行历史页\n状态、产物、失败步骤、fallback"]
    Audit --> History
    Orchestrator --> History

    DeepRun --> DeepSeq["后台顺序重跑\n三位交易 Agent -> Chairman -> Red Team"]
    DeepSeq --> Recs
```

## 2. 运行入口区别

```mermaid
flowchart LR
    Home["主页运行早/晚报告"] --> HomeApi["/api/run-stream"]
    HomeApi --> Full["uv run orchestrator run --type full"]
    Full --> FullLLM["交易 Agent 可用 LLM\nResearch deterministic\nChairman/Red Team 默认 --no-llm"]

    Deep["深度研究页回填后重跑"] --> RerunApi["/api/deep-research/rerun-stream"]
    RerunApi --> Rerun["依次执行三位交易 Agent\nChairman\nRed Team"]
    Rerun --> RerunLLM["默认启用 LLM\n除非下拉选择 --no-llm"]

    Agent["单 Agent 调试"] --> AgentApi["/api/agent-stream"]
    AgentApi --> AgentCmd["research-agent 或 trading-* 或 chairman 或 red-team"]
```

实际影响：

- 主页完整跑适合从零生成当天信号、推荐、Brief、Audit。
- 深度研究回填后重跑适合在 Perplexity 回填后，让三位交易 Agent 重新读取回填内容，再生成新的 Brief/Audit。
- 单 Agent 调试适合排查某一步，不等价于完整系统跑。

## 3. 数据产物流

```mermaid
flowchart TD
    Pool["股池\nmaster_pool.yaml"] --> Scan["Research Agent 扫描"]
    Price["公开价格/成交量"] --> Scan

    Scan --> RS["research_signal\nRS-*.yaml"]
    Scan --> PR["Perplexity prompt\nPR-*.yaml"]
    Scan --> RR["研究运行摘要\nRESEARCH-*.yaml"]

    PR --> Manual["Nepha 手动去 Perplexity 研究"]
    Manual --> Filled["filled.yaml\n答案、来源、prompt_text"]
    Manual --> Skipped["skipped.yaml\n跳过原因"]

    Filled --> Context["PerplexityContext\nfilled/skipped/pending"]
    Skipped --> Context
    RS --> Context

    Context --> Fengliu["冯柳 Agent"]
    Context --> Wanmu["万木 Agent"]
    Context --> Liguofei["李国飞 Agent"]

    Fengliu --> R1["recommendation YAML"]
    Wanmu --> R2["recommendation YAML"]
    Liguofei --> R3["recommendation YAML"]

    R1 --> Brief["Chairman Brief"]
    R2 --> Brief
    R3 --> Brief
    RS --> Brief

    Brief --> Audit["Red Team Audit"]
    R1 --> Audit
    R2 --> Audit
    R3 --> Audit
    RS --> Audit
```

关键原则：

- Research Agent 只负责发现“值得研究的异常”，不负责交易判断。
- Perplexity 只通过人工回填进入系统，系统不自动联网问 Perplexity。
- Trading Agent 必须引用 4.1 信号和 Perplexity 状态。
- Chairman 汇总分歧，不替 Nepha 做最终交易决策。
- Red Team 做风险和规则审计，不负责给买卖建议。

## 4. LLM 工作机制

```mermaid
sequenceDiagram
    participant Agent as Trading/Chairman/RedTeam
    participant Prompt as Methodology + User Prompt
    participant Env as .env
    participant Provider as LLM Provider
    participant Codex as Codex CLI / OpenAI
    participant Validator as Schema Validator
    participant Disk as Local YAML/Markdown

    Agent->>Prompt: 读取方法论 prompt
    Agent->>Prompt: 拼入 research_signal、价量数据、PerplexityContext
    Agent->>Env: 读取 LLM_PROVIDER / LLM_MODEL

    alt no_llm 开启
        Agent->>Agent: 走 deterministic fallback
        Agent->>Disk: 写 watch/avoid/abstain 结果
    else LLM_PROVIDER=codex_cli
        Agent->>Provider: build_llm_client_from_env()
        Provider->>Codex: codex exec --model LLM_MODEL
        Codex-->>Provider: 返回严格 JSON 或文本
        Provider-->>Agent: final answer
        Agent->>Validator: 解析 JSON + Pydantic 校验
        alt 校验通过
            Validator-->>Agent: 合法 payload
            Agent->>Agent: 试运行规则强制 long/short 降级
            Agent->>Disk: 写推荐/报告/审计
        else 格式不合格
            Agent->>Codex: 带校验错误重试修复
            Codex-->>Agent: 修复后的 JSON
            Agent->>Validator: 再校验
            alt 仍失败
                Agent->>Agent: 强制 abstain 或 rules-only fallback
                Agent->>Disk: 写 validation_failure / fallback 记录
            end
        end
    else LLM_PROVIDER=openai
        Provider->>Codex: OpenAI Chat Completions
        Codex-->>Provider: 返回模型输出
        Provider-->>Agent: final answer
    else LLM_PROVIDER=local
        Provider-->>Agent: 当前 local provider 未配置，触发 fallback
    end
```

LLM 在系统里的职责分工：

- Research Agent：当前主要是 deterministic 价量扫描；会加载方法论 prompt 并记录上下文，但不依赖 LLM 生成信号。
- 三位交易 Agent：可调用 LLM，根据各自方法论解释 4.1 信号、价量证据和 Perplexity 回填；输出必须通过 schema 校验。
- Chairman：可调用 LLM 写分歧叙事；核心共识计算、权重和升级路由仍是 deterministic。
- Red Team：可调用 LLM 做方法论挑刺；硬规则审计 deterministic，LLM 失败时走 rules-only fallback。

## 5. Codex CLI Provider 如何工作

```mermaid
flowchart TD
    Env[".env\nLLM_PROVIDER=codex_cli\nLLM_MODEL=gpt-5.5"] --> Builder["build_llm_client_from_env"]
    Builder --> Client["CodexCliClient"]
    Client --> Prompt["Provider Prompt\n禁止改文件\n禁止外部服务\n严格返回 JSON"]
    Prompt --> Exec["codex exec\n--ask-for-approval never\n--sandbox workspace-write\n--output-last-message temp_file"]
    Exec --> Model["gpt-5.5 或 .env 指定模型"]
    Model --> Output["最后一条消息"]
    Output --> Parser["JSON parser / text consumer"]
    Parser --> Validator["Pydantic schema validation"]
    Validator -->|"通过"| Use["写入业务产物"]
    Validator -->|"失败"| Repair["把错误喂回模型重试"]
    Repair --> Validator
    Validator -->|"多次失败"| Fallback["abstain / rules-only / template fallback"]
```

重点限制：

- Codex CLI 在这里被当成“本地 LLM provider”，不是执行 Agent。
- Provider prompt 明确要求不修改文件、不跑迁移、不调用外部服务。
- 交易 Agent 要求 JSON；Chairman/Red Team 可生成文本叙事，但最终仍会落成 Markdown + JSON。
- `CODEX_PROVIDER_REASONING_EFFORT` 默认是 `low`，用于避免一次跑太久。

## 6. 试运行安全闸门

```mermaid
flowchart TD
    LLMOut["LLM 原始输出"] --> Parse["解析 JSON"]
    Parse --> Schema["Schema 校验"]
    Schema --> Policy["试运行策略层"]
    Policy --> LongCheck{"direction 是 long/short?"}
    LongCheck -->|"是"| Downgrade["降级为 watch\nposition_size_pct=0\n记录 downgrade_reason"]
    LongCheck -->|"否"| Allowed{"watch / avoid / abstain?"}
    Allowed -->|"是"| Write["写 recommendation YAML"]
    Allowed -->|"否"| Abstain["强制 abstain\n记录格式/策略失败"]
    Downgrade --> Write
    Abstain --> Write
    Write --> RedAudit["Red Team 检查\nlong 禁用违规\n格式失败\n证据不足\nsource_url 缺失"]
```

这层是为了避免未校准系统给出真实交易指令。即使 LLM 认为应该买入，第一阶段也只能进入 `watch`。

## 7. 深度研究回填后重跑

```mermaid
sequenceDiagram
    participant UI as 深度研究页
    participant File as 本地文件系统
    participant Signal as Research Signal
    participant Agents as 三位交易 Agent
    participant Chairman as Chairman
    participant Red as Red Team
    participant History as 运行历史

    UI->>File: 保存 PR-*_filled.yaml 或 PR-*_skipped.yaml
    File->>Signal: 同步 prompts_filled_back / prompts_pending / coverage_ratio
    UI->>History: 创建 deep_research_rerun 运行记录
    UI->>Agents: 重跑冯柳、万木、李国飞
    Agents->>File: 读取 research_signal + PerplexityContext
    Agents->>File: 写新的 recommendation YAML
    Agents->>Chairman: 交给 Chairman 汇总
    Chairman->>File: 写 BRIEF-*.md + .json
    Chairman->>Red: 交给 Red Team 审计
    Red->>File: 写 AUDIT-*.md + .json
    Red->>History: 标记 completed / failed / cancelled
```

回填后重跑主要解决的问题：

- Agent 不能再说“未回填”，因为 `PerplexityContext` 会读取 `filled.yaml`。
- 旧的同日期 recommendation / brief / audit 会在重跑前清理，避免历史产物混在一起。
- 如果浏览器断开，后台任务仍继续跑；历史页用 run_id 查看最终结果。

## 8. 产物路径速查

| 阶段 | 输入 | 输出 |
| --- | --- | --- |
| 股池 | Web UI 股池管理 / `master_pool.yaml` | `data/stock_pool/master_pool.yaml` |
| 4.1 扫描 | 股池 + 公开价量 | `data/research_signals/RS-*.yaml` |
| Perplexity prompt | 触发的 4.1 信号 | `data/pull_requests/PR-*.yaml` |
| 人工回填 | Perplexity 答案或跳过原因 | `data/perplexity_results/PR-*_filled.yaml` / `PR-*_skipped.yaml` |
| 三位交易 Agent | 4.1 信号 + 回填状态 + 方法论 + LLM | `data/recommendations/YYYYMMDD/{fengliu,wanmu,liguofei}/*.yaml` |
| Chairman | recommendations + research_signals | `data/briefs/YYYYMMDD/BRIEF-*.md` + `.json` |
| Red Team | brief + recommendations + research_signals | `data/red_team_audits/YYYYMMDD/AUDIT-*.md` + `.json` |
| 运行历史 | Orchestrator run log + step log | `data/orchestrator/runs.db`、`data/orchestrator/logs/*` |

## 9. 一句话版

系统先用公开价量从股池里筛出异常信号，再把需要解释的原因交给 Nepha 手动 Perplexity 回填；三位交易 Agent 读取信号和回填内容，用各自方法论和 LLM 做保守判断；Chairman 汇总共识与分歧；Red Team 审计规则、证据和格式风险；所有结果都落在本地文件和运行历史里。
