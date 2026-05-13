# Agent Trading System 本地运行说明书

这份说明书按“完全不懂代码也能照着跑”的标准写。最新版已经带本地 Web UI：你可以像使用普通网页一样点按钮运行系统，也可以继续使用命令行。

## 0. 这个项目到底是什么

这是一个本地运行的多 Agent 投资决策系统。它的核心仍然是本地命令行流水线，最新版额外提供了一个本地网页控制台，地址是 `http://127.0.0.1:7777`。

它的工作方式是：

1. `research-agent` 先从你的股池里挑出研究对象，生成研究信号。
2. `trading-fengliu` 按冯柳方法论输出一份交易建议。
3. `trading-wanmu` 按万木方法论输出一份交易建议。
4. `trading-liguofei` 按李国飞方法论输出一份交易建议。
5. `chairman` 汇总三份建议，生成 Morning Brief 或 Evening Brief。
6. `red-team` 对 Chairman 的结论做风险审计。
7. `orchestrator` 是总开关，一次性把上面所有步骤跑完。

你日常最常用的启动命令是：

```bash
uv run python webui.py
```

打开网页后，点击「运行早间报告」或「运行晚间报告」即可。

如果你仍然想用命令行，一键跑完整 Morning Brief 的命令是：

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
uv sync --extra dev --extra webui
```

你可以把它理解为“安装这个项目需要的零件”。

成功时，终端通常会显示安装完成，不会一直报红色错误。

如果提示 `uv: command not found`，说明电脑没有 `uv`。先安装：

```bash
brew install uv
```

然后再运行：

```bash
uv sync --extra dev --extra webui
```

## 3. 最推荐的日常使用方式：打开 Web UI

安装完成后，在项目目录里运行：

```bash
uv run python webui.py
```

看到类似下面这一行，说明网页服务已经启动：

```text
Uvicorn running on http://127.0.0.1:7777
```

然后用浏览器打开：

```text
http://127.0.0.1:7777
```

Web UI 顶部有五个页面：

- 「主页」：选择日期，一键运行早间报告或晚间报告，实时查看日志，运行完成后直接阅读 Brief 和 Red Team Audit。
- 「运行历史」：查看最近 10 条运行记录，包括 run_id、日期、brief-type 和 status。
- 「股池管理」：读取并编辑 `data/stock_pool/master_pool.yaml`，支持港股、美股、A 股参考、观察池四类股票。
- 「深度研究」：查看 Research Agent 生成的 Perplexity prompt，复制问题、粘贴答案、保存回填，并触发回填后重跑。
- 「环境配置」：切换 `LLM_PROVIDER=local|openai|codex_cli`，设置 `LLM_MODEL` / `OPENAI_API_KEY`，查看 Codex 登录状态或启动 Codex 登录。API Key 只写入本地 `.env`，页面只显示脱敏状态。

### 3.1 第一次用 Web UI 跑 Morning Brief

1. 打开 `http://127.0.0.1:7777`。
2. 日期默认是今天，也可以手动选择。
3. 点击「运行早间报告」。
4. 页面下方会实时滚动显示命令行日志。
5. 看到 `status=completed` 后，右侧报告阅读器会展示 Morning Brief 和 Red Team Audit。

### 3.2 第一次用 Web UI 跑 Evening Brief

1. 打开 `http://127.0.0.1:7777`。
2. 点击「运行晚间报告」。
3. 看到 `status=completed` 后，报告阅读器会展示 Evening Brief 和对应 Red Team Audit。

### 3.3 停止 Web UI

回到启动 Web UI 的终端窗口，按：

```text
Control + C
```

即可停止本地网页服务。

## 4. 如果你想用命令行试跑

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

## 5. 跑完以后去哪里看结果

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

Web UI 也会自动读取这些 Markdown 文件，并在「报告阅读器」里渲染成网页内容。

## 6. 各个输出文件分别是什么意思

### 6.1 Morning Brief

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

### 6.2 Red Team Audit

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

### 6.3 三个交易 Agent 的建议

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

### 6.4 研究信号

位置：

```text
data/research_signals/
```

这是 4.1 研究上游生成的输入。

### 6.5 需要手动补充 Perplexity 研究的问题

位置：

```text
data/pull_requests/
```

注意：系统不会自动调用 Perplexity。

如果它觉得需要更深入研究，会把问题写到这里，让你自己决定要不要拿去 Perplexity 里查。

最新版 Web UI 已经把这条人工研究闭环接进来。你可以进入「深度研究」页面：

1. 查看 `data/pull_requests/*.yaml` 里的 prompt。
2. 点击「复制 Prompt」，去 Perplexity 做深入研究。
3. 把 Perplexity 答案粘贴回页面。
4. 点击「保存回填」，系统会写入：

```text
data/perplexity_results/PROMPT_ID_filled.yaml
```

如果你决定这条 prompt 暂不研究，可以点击「标记跳过」，系统会写入：

```text
data/perplexity_results/PROMPT_ID_skipped.yaml
```

保存回填后，点击「重跑交易 Agent + Chairman + Red Team」。三位交易 Agent 会读取 `data/perplexity_results/` 里的结果，不再把 Perplexity 结果当成“无”。

## 7. 日常怎么使用

### 7.1 推荐：每天从 Web UI 运行

```bash
cd ~/agent-trading-system
uv run python webui.py
```

然后打开 `http://127.0.0.1:7777`：

- 早上点「运行早间报告」
- 晚上点「运行晚间报告」
- 跑完后直接在页面阅读 Brief 和 Red Team Audit
- Research Agent 生成研究问题后，进入「深度研究」复制 prompt、保存 Perplexity 回答、重跑分析
- 需要修改股池时，进入「股池管理」
- 需要切换 local/openai/codex_cli 或检查 Codex 登录时，进入「环境配置」

### 7.2 命令行：每天早上跑 Morning Brief

```bash
cd ~/agent-trading-system
LLM_PROVIDER=local uv run orchestrator run --type full --brief-type morning --date $(date +%F)
open data/briefs/$(date +%Y%m%d)/BRIEF-$(date +%Y%m%d)-AM.md
open data/red_team_audits/$(date +%Y%m%d)/AUDIT-$(date +%Y%m%d)-AM.md
```

### 7.3 命令行：跑 Evening Brief

```bash
cd ~/agent-trading-system
LLM_PROVIDER=local uv run orchestrator run --type full --brief-type evening --date $(date +%F)
open data/briefs/$(date +%Y%m%d)/BRIEF-$(date +%Y%m%d)-PM.md
open data/red_team_audits/$(date +%Y%m%d)/AUDIT-$(date +%Y%m%d)-PM.md
```

### 7.4 命令行：只想看最近运行记录

```bash
cd ~/agent-trading-system
uv run orchestrator history --data-dir data --tail 5
```

成功运行会显示：

```text
"status": "completed"
```

## 8. 股池在哪里改

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

最推荐的方式是在 Web UI 的「股池管理」页面修改并保存。

如果你想直接改 YAML，照着原格式加就行，比如港股：

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

## 9. 如果你想让它用 OpenAI API 或 Codex CLI

第一次建议先别开。等本地保守模式跑通后再开。

### 9.1 使用 OpenAI API

最简单的方式是在 Web UI 的「环境配置」页面：

1. 把 LLM Provider 选成 `openai`。
2. 填写 `LLM_MODEL`，例如 `gpt-5.5`。
3. 填写 `OPENAI_API_KEY`。
4. 点击「保存 .env」。

保存后，API Key 只会写入本机 `.env` 文件，前端不会存储，页面也只显示脱敏后的 Key 状态。

如果你想手动配置，也可以继续按下面方式操作。

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

### 9.2 使用 Codex CLI 登录态

如果本机已经安装并登录 Codex CLI，可以不填写 `OPENAI_API_KEY`，直接让后端通过本机登录态调用 `codex exec`。

在 Web UI 里：

1. 进入「环境配置」。
2. 查看「Codex 登录状态」。状态会显示 `ChatGPT 登录`、`API key 登录`、`未登录` 或 `codex 不可用`。
3. 如果未登录，点击「启动 Codex 登录」，按页面日志里的 device auth 提示完成登录。
4. LLM Provider 选择 `codex_cli`。
5. `LLM_MODEL` 可以留空，使用 Codex CLI 默认配置；也可以填写具体模型，例如 `gpt-5.5`。
6. 点击「保存 .env」。

手动配置 `.env` 时可以这样写：

```text
LLM_PROVIDER=codex_cli
LLM_MODEL=
OPENAI_API_KEY=
```

Codex 的登录信息由 `~/.codex/` 管理，Web UI 只启动登录流程和显示 CLI 输出，不保存 token，也不会读取或展示密钥。

## 10. 如果你只想单独跑某一个 Agent

一般不需要这么做，除非排查问题。Web UI 的「单 Agent」区域已经支持单独触发 research-agent、冯柳、万木、李国飞、Chairman、Red Team，并且可以选择 `--no-llm`。

### 10.1 只跑研究 Agent

```bash
uv run research-agent run --type scan --no-llm
```

输出：

```text
data/research_signals/
data/pull_requests/
data/perplexity_results/
```

### 10.2 只跑冯柳 Agent

必须先有 research signal。

```bash
uv run trading-fengliu run --no-llm
```

输出：

```text
data/recommendations/YYYYMMDD/fengliu/
```

### 10.3 只跑万木 Agent

```bash
uv run trading-wanmu run --no-llm
```

输出：

```text
data/recommendations/YYYYMMDD/wanmu/
```

### 10.4 只跑李国飞 Agent

```bash
uv run trading-liguofei run --no-llm
```

输出：

```text
data/recommendations/YYYYMMDD/liguofei/
```

### 10.5 只跑 Chairman

必须先有 research signal 和三份 recommendation。

```bash
uv run chairman generate-brief --type morning --date $(date +%F) --no-llm
```

### 10.6 只跑 Red Team

必须先有 Chairman brief。

```bash
uv run red-team audit --type morning --date $(date +%F) --no-llm
```

## 11. 最常见问题

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
uv sync --extra dev --extra webui
```

### 问题 3：Web UI 打不开 `http://127.0.0.1:7777`

先确认终端里是不是还在运行：

```bash
uv run python webui.py
```

如果提示端口被占用，可以先找出占用进程：

```bash
lsof -ti tcp:7777
```

再把输出发给 Codex，让它帮你判断是否可以停止旧进程。

### 问题 4：页面运行报告后一直没有完成

先看页面下方实时日志。如果日志里出现错误，把整段日志发给 Codex。

也可以在终端里查看最近运行记录：

```bash
uv run orchestrator history --data-dir data --tail 10
```

### 问题 5：提示找不到 stock pool

检查这个文件是否存在：

```bash
ls data/stock_pool/master_pool.yaml
```

如果不存在，从 GitHub 重新拉：

```bash
git pull
```

### 问题 6：为什么我填了过去日期，但是没生成对应日期报告？

不要随便填过去日期。

业务 Agent 默认按电脑今天日期写输出。最稳妥的方式是永远用：

```bash
--date $(date +%F)
```

也就是今天。

### 问题 7：我想重新跑一遍，旧结果会不会坏？

不会影响源码。

但同一天重复跑，会覆盖或追加部分同名运行产物。日常使用没关系。

### 问题 8：我想清空运行结果，从头再来

Web UI 主页里有「清除所选日期运行结果」按钮。它只会清理当前选择日期的运行产物，不会删除股池，也不会删除其他日期。

如果你确定要用命令行清空全部运行结果，可以运行下面命令。注意：这会删除所有历史运行结果，不只是今天。

```bash
rm -rf data/agent_logs data/research_signals data/recommendations data/pull_requests data/perplexity_results data/briefs data/red_team_audits data/orchestrator data/notifications data/errors
```

不要删除：

```text
data/stock_pool/master_pool.yaml
```

## 12. 怎么确认项目本身没坏

运行测试：

```bash
uv run python -m pytest -q
```

看到类似下面这样就是正常：

```text
88 passed
```

运行格式检查：

```bash
uv run ruff check chairman red_team orchestrator business_agents tests webui.py
```

看到：

```text
All checks passed!
```

就是正常。

Web UI 也可以单独做一次快速语法检查：

```bash
uv run python -m py_compile webui.py
```

## 13. 你现在这台机器的已验证结果

我已经在这台机器上验证过完整流水线和 Web UI。

命令：

```bash
LLM_PROVIDER=local uv run orchestrator run --type full --brief-type morning --date 2026-05-13
```

结果：

```text
run_id=RUN-20260513-60b5a1c1 status=completed
```

说明：

- 研究 Agent 成功生成 research signal
- 三个交易 Agent 成功生成 recommendation
- Chairman 成功生成 Morning Brief
- Red Team 成功生成 Audit
- Orchestrator 记录为 completed
- `uv run python webui.py` 可启动本地网页服务
- 浏览器打开 `http://127.0.0.1:7777` 可看到主页、运行历史、股池管理、深度研究、环境配置

已验证检查：

```text
uv run ruff check chairman red_team orchestrator business_agents tests webui.py
uv run python -m pytest -q
88 passed
```

Codex CLI provider 已做过冒烟验证：

```text
LLM_PROVIDER=codex_cli research-agent run --type scan
LLM_PROVIDER=codex_cli trading-fengliu run
LLM_PROVIDER=codex_cli chairman generate-brief
```

这些路径都能通过本机 Codex 登录态触发 LLM，并继续由 Python pipeline 做 schema 校验和产物写入。

## 14. 一句话版

以后你只要想本地用网页跑这个系统，就打开终端，复制这三行：

```bash
cd ~/agent-trading-system
uv sync --extra dev --extra webui
uv run python webui.py
```

然后打开：

```text
http://127.0.0.1:7777
```

想继续用命令行的话，复制：

```bash
LLM_PROVIDER=local uv run orchestrator run --type full --brief-type morning --date $(date +%F)
```
