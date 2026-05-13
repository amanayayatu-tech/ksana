# Agent Trading System 本地运行说明书

这份说明书按“完全不懂代码也能照着跑”的标准写。你只需要复制命令、粘贴到终端、回车。

## 0. 这个项目到底是什么

这是一个本地运行的多 Agent 投资决策系统，不是网页，也不是 App。

它的工作方式是：

1. `research-agent` 先从你的股池里挑出研究对象，生成研究信号。
2. `trading-fengliu` 按冯柳方法论输出一份交易建议。
3. `trading-wanmu` 按万木方法论输出一份交易建议。
4. `trading-liguofei` 按李国飞方法论输出一份交易建议。
5. `chairman` 汇总三份建议，生成 Morning Brief 或 Evening Brief。
6. `red-team` 对 Chairman 的结论做风险审计。
7. `orchestrator` 是总开关，一次性把上面所有步骤跑完。

你日常最常用的命令只有一个：

```bash
LLM_PROVIDER=local uv run orchestrator run --type full --brief-type morning --date $(date +%F)
```

## 1. 先确认你在哪里

这个项目在你电脑上的路径是：

```text
/Users/peachy/agent-trading-system
```

打开终端后，先进入项目目录：

```bash
cd ~/agent-trading-system
```

如果你不知道终端在哪里：

1. 打开 Mac 的“终端”或 Warp。
2. 粘贴上面这一行。
3. 回车。

如果你看到类似 `no such file or directory`，说明目录不在这里。可以从 GitHub 重新下载：

```bash
cd ~
git clone https://github.com/amanayayatu-tech/worldpay77.git agent-trading-system
cd ~/agent-trading-system
```

## 2. 第一次运行前，只做一次安装

进入项目目录后，运行：

```bash
uv sync --extra dev
```

你可以把它理解为“安装这个项目需要的零件”。

成功时，终端通常会显示安装完成，不会一直报红色错误。

如果提示 `uv: command not found`，说明电脑没有 `uv`。先安装：

```bash
brew install uv
```

然后再运行：

```bash
uv sync --extra dev
```

## 3. 最推荐的第一次试跑方式

第一次不要接 OpenAI API，不要联网推理，先用本地保守模式跑通。

在项目目录里运行：

```bash
LLM_PROVIDER=local uv run orchestrator run --type full --brief-type morning --date $(date +%F)
```

看到类似下面这一行，就是成功：

```text
run_id=RUN-20260513-xxxxxxx status=completed trigger_signal=
```

你只需要看 `status=completed`。

如果不是 `completed`，先不要猜，直接运行：

```bash
uv run orchestrator history --data-dir data --tail 5
```

把输出发给 Codex，让它继续排查。

## 4. 跑完以后去哪里看结果

结果都在 `data/` 文件夹里。

最重要的是这两个文件：

```text
data/briefs/YYYYMMDD/BRIEF-YYYYMMDD-AM.md
data/red_team_audits/YYYYMMDD/AUDIT-YYYYMMDD-AM.md
```

其中 `YYYYMMDD` 是日期，比如 2026 年 5 月 13 日就是：

```text
data/briefs/20260513/BRIEF-20260513-AM.md
data/red_team_audits/20260513/AUDIT-20260513-AM.md
```

你可以直接在 Finder 里打开，也可以用命令打开今天的 Morning Brief：

```bash
open data/briefs/$(date +%Y%m%d)/BRIEF-$(date +%Y%m%d)-AM.md
```

打开今天的 Red Team 审计：

```bash
open data/red_team_audits/$(date +%Y%m%d)/AUDIT-$(date +%Y%m%d)-AM.md
```

## 5. 各个输出文件分别是什么意思

### 5.1 Morning Brief

位置：

```text
data/briefs/YYYYMMDD/BRIEF-YYYYMMDD-AM.md
```

这是你最应该看的主报告。

它告诉你：

- 今天有哪些标的被研究
- 三个交易 Agent 分别怎么看
- 它们有没有分歧
- Chairman 如何汇总
- 哪些地方需要你人工判断

### 5.2 Red Team Audit

位置：

```text
data/red_team_audits/YYYYMMDD/AUDIT-YYYYMMDD-AM.md
```

这是风险审计报告。

它告诉你：

- Chairman 有没有跳过关键风险
- 三个交易 Agent 有没有违反硬规则
- 是否有证据未验证
- 是否需要你暂停、复核、补研究

### 5.3 三个交易 Agent 的建议

位置：

```text
data/recommendations/YYYYMMDD/fengliu/
data/recommendations/YYYYMMDD/wanmu/
data/recommendations/YYYYMMDD/liguofei/
```

分别对应：

- 冯柳方法论
- 万木方法论
- 李国飞方法论

### 5.4 研究信号

位置：

```text
data/research_signals/
```

这是 4.1 研究上游生成的输入。

### 5.5 需要手动补充 Perplexity 研究的问题

位置：

```text
data/pull_requests/
```

注意：系统不会自动调用 Perplexity。

如果它觉得需要更深入研究，会把问题写到这里，让你自己决定要不要拿去 Perplexity 里查。

## 6. 日常怎么使用

### 6.1 每天早上跑 Morning Brief

```bash
cd ~/agent-trading-system
LLM_PROVIDER=local uv run orchestrator run --type full --brief-type morning --date $(date +%F)
open data/briefs/$(date +%Y%m%d)/BRIEF-$(date +%Y%m%d)-AM.md
open data/red_team_audits/$(date +%Y%m%d)/AUDIT-$(date +%Y%m%d)-AM.md
```

### 6.2 跑 Evening Brief

```bash
cd ~/agent-trading-system
LLM_PROVIDER=local uv run orchestrator run --type full --brief-type evening --date $(date +%F)
open data/briefs/$(date +%Y%m%d)/BRIEF-$(date +%Y%m%d)-PM.md
open data/red_team_audits/$(date +%Y%m%d)/AUDIT-$(date +%Y%m%d)-PM.md
```

### 6.3 只想看最近运行记录

```bash
cd ~/agent-trading-system
uv run orchestrator history --data-dir data --tail 5
```

成功运行会显示：

```text
"status": "completed"
```

## 7. 股池在哪里改

股池文件是：

```text
data/stock_pool/master_pool.yaml
```

系统只会研究这个文件里的股票。

最简单的理解：

- `hk_stocks`：港股主股池，可以研究、可以输出建议
- `us_stocks`：美股主股池，可以研究、可以输出建议
- `a_stocks_reference_only`：A 股只做案例参考，不会输出交易建议
- `watchlist`：观察池，只能 watch 或 abstain，不会 long/short

修改股池时，照着原格式加就行，比如港股：

```yaml
hk_stocks:
  - ticker: "0700.HK"
    name: "Tencent Holdings"
    tags: ["internet", "platform"]
```

美股：

```yaml
us_stocks:
  - ticker: "BABA"
    name: "Alibaba ADR"
    tags: ["internet", "platform"]
```

不要随便改缩进。YAML 文件最怕缩进错。

## 8. 如果你想让它用 OpenAI / GPT-5.5

第一次建议先别开。等本地保守模式跑通后再开。

复制配置文件：

```bash
cp .env.example .env
```

打开 `.env`，填入你的 OpenAI API Key：

```text
LLM_PROVIDER=openai
LLM_MODEL=gpt-5.5
OPENAI_API_KEY=这里填你的key
```

然后运行：

```bash
uv run orchestrator run --type full --brief-type morning --date $(date +%F)
```

注意：

- 没有 API Key 时，系统也能跑，只是会用保守 fallback。
- 当前编排里 Chairman 和 Red Team 默认用确定性模板，避免最后总结阶段乱发挥。
- 业务 Agent 会优先尝试 LLM；如果失败，会自动降级，不应该把整个系统跑崩。

## 9. 如果你只想单独跑某一个 Agent

一般不需要这么做，除非排查问题。

### 9.1 只跑研究 Agent

```bash
uv run research-agent run --type scan --no-llm
```

输出：

```text
data/research_signals/
data/pull_requests/
```

### 9.2 只跑冯柳 Agent

必须先有 research signal。

```bash
uv run trading-fengliu run --no-llm
```

输出：

```text
data/recommendations/YYYYMMDD/fengliu/
```

### 9.3 只跑万木 Agent

```bash
uv run trading-wanmu run --no-llm
```

输出：

```text
data/recommendations/YYYYMMDD/wanmu/
```

### 9.4 只跑李国飞 Agent

```bash
uv run trading-liguofei run --no-llm
```

输出：

```text
data/recommendations/YYYYMMDD/liguofei/
```

### 9.5 只跑 Chairman

必须先有 research signal 和三份 recommendation。

```bash
uv run chairman generate-brief --type morning --date $(date +%F) --no-llm
```

### 9.6 只跑 Red Team

必须先有 Chairman brief。

```bash
uv run red-team audit --type morning --date $(date +%F) --no-llm
```

## 10. 最常见问题

### 问题 1：我看到 `status=completed`，还要做什么？

不用做什么，说明完整跑通了。

接下来打开：

```bash
open data/briefs/$(date +%Y%m%d)/BRIEF-$(date +%Y%m%d)-AM.md
open data/red_team_audits/$(date +%Y%m%d)/AUDIT-$(date +%Y%m%d)-AM.md
```

### 问题 2：提示找不到 `uv`

运行：

```bash
brew install uv
```

然后重新运行：

```bash
uv sync --extra dev
```

### 问题 3：提示找不到 stock pool

检查这个文件是否存在：

```bash
ls data/stock_pool/master_pool.yaml
```

如果不存在，从 GitHub 重新拉：

```bash
git pull
```

### 问题 4：为什么我填了过去日期，但是没生成对应日期报告？

不要随便填过去日期。

业务 Agent 默认按电脑今天日期写输出。最稳妥的方式是永远用：

```bash
--date $(date +%F)
```

也就是今天。

### 问题 5：我想重新跑一遍，旧结果会不会坏？

不会影响源码。

但同一天重复跑，会覆盖或追加部分同名运行产物。日常使用没关系。

### 问题 6：我想清空运行结果，从头再来

只清运行结果，不清股池：

```bash
rm -rf data/agent_logs data/research_signals data/recommendations data/pull_requests data/briefs data/red_team_audits data/orchestrator data/notifications data/errors
```

不要删除：

```text
data/stock_pool/master_pool.yaml
```

## 11. 怎么确认项目本身没坏

运行测试：

```bash
uv run python -m pytest -q
```

看到类似下面这样就是正常：

```text
76 passed
```

运行格式检查：

```bash
uv run ruff check chairman red_team orchestrator business_agents tests
```

看到：

```text
All checks passed!
```

就是正常。

## 12. 你现在这台机器的已验证结果

我已经在这台机器上跑过一次完整流水线。

命令：

```bash
LLM_PROVIDER=local uv run orchestrator run --type full --brief-type morning --date 2026-05-13
```

结果：

```text
run_id=RUN-20260513-46d55a9c status=completed
```

说明：

- 研究 Agent 成功生成 research signal
- 三个交易 Agent 成功生成 recommendation
- Chairman 成功生成 Morning Brief
- Red Team 成功生成 Audit
- Orchestrator 记录为 completed

## 13. 一句话版

以后你只要想本地跑这个系统，就打开终端，复制这三行：

```bash
cd ~/agent-trading-system
uv sync --extra dev
LLM_PROVIDER=local uv run orchestrator run --type full --brief-type morning --date $(date +%F)
```

然后打开报告：

```bash
open data/briefs/$(date +%Y%m%d)/BRIEF-$(date +%Y%m%d)-AM.md
open data/red_team_audits/$(date +%Y%m%d)/AUDIT-$(date +%Y%m%d)-AM.md
```
