# UI_REDESIGN_PLAN.md - WorldPay IC / ResearchOS UI Redesign Plan

## Executive Summary

ResearchOS already has the right workflow primitives for a financial intelligence power tool: run orchestration, human-in-the-loop research fill, report review, cost visibility, stock universe editing, and learning review. The current UI is constrained by monolithic FastAPI/Jinja templates, inline CSS/JS, overloaded pages, inconsistent states, and limited observability patterns compared with LangSmith, Dify, and Flowise. The recommended path is to stabilize and refactor the existing FastAPI/Jinja UI first, then migrate to a React/Next.js frontend only when the interaction model needs reusable drawers, trace trees, advanced tables, and richer workflow visualization.

## Evidence Read

- `webui.py` was read in full: 3042 lines, 108 KB.
- All templates were read in full: `base.html`, `index.html`, `deep_research.html`, `history.html`, `stock_pool.html`, `learning.html`, `timeline.html`, `guide.html`, and `env.html`.
- Architecture context was checked in `ARCHITECTURE.md`, `README.md`, `SYSTEM_FLOW.md`, `LOCAL_RUNBOOK.md`, and `AGENTS.md`.
- The actual frontend is FastAPI + Jinja templates with inline CSS and vanilla JavaScript, not Gradio.
- Implementation risk evidence: `webui.py` currently contains 34 route decorators, 5 `StreamingResponse` paths, 5 async subprocess launch sites, 3 blocking `subprocess.run` sites, 4 direct SQLite connection sites, 7 `RunLog` construction sites, 10 `write_text` calls, 3 `unlink` calls, and 1 `shutil.rmtree` cleanup path.
- Template risk evidence: operational templates contain substantial inline client logic: `index.html` has about 36 functions, 7 fetch calls, and 1 EventSource; `deep_research.html` has about 33 functions, 5 fetch calls, and 1 EventSource; `history.html` has about 29 functions and 4 fetch calls; `env.html` has 1 EventSource for Codex login.

## Current UI Inventory

### Pages And Primary Jobs

| Page | Route | Current job | Primary UI patterns |
| --- | --- | --- | --- |
| Task Flow | `/` | Run research scan, fill selected Deep Research prompts, rerun committee, read latest reports, view ops snapshot, run single agents, cleanup artifacts | Workflow hero, action row, progress panel, terminal log, prompt card list, fill form, metrics, memory ledger, markdown/report links, advanced controls |
| Deep Research Inbox | `/deep-research` | Filter prompt queue, copy prompt, paste or drag research result, save/skip, rerun committee | Command banner, metric strip, table queue, split workbench, textareas, drop zone, knowledge receipt, SSE rerun terminal |
| Report Center | `/history` | Inspect recent runs, open report artifacts, view run progress and LLM cost | Data table, artifact modal, iframe report viewer, run detail modal, tabs, progress timeline, cost table |
| Stock Pool | `/stock-pool` | Edit stock universe and watchlist | Inline editable tables, add/delete rows, save status |
| Review Library | `/learning` | Review decision cases, outcome snapshots, top tickers, learning state | Metric strip, ledger rows, data table, refresh actions |
| Ticker Timeline | `/timeline/{ticker}` | Review per-stock knowledge, decisions, outcomes, open questions | Metric strip, ledger event list |
| Usage Guide | `/guide` | Explain product workflow and sample reports | Hero, decorative visual diagram, cards, sample report cards, partner cards |
| LLM API Settings | `/env` | Configure local/OpenAI/Codex provider, check health, run Codex login | Settings form, state table, SSE terminal |

### Layout Patterns Present

| Pattern | Where | Current behavior |
| --- | --- | --- |
| Fixed sidebar app frame | `base.html` | 244 px left nav, sticky full-height sidebar, sticky context bar |
| Dense panel shell | All operational pages | `.panel`, `.panel-head`, `.panel-body` frame most content |
| Dashboard metrics | Home, Inbox, Learning, Timeline | Four-column `.metric-strip` cells with mono numeric values |
| Split workbench | Inbox, Env, Home gate | Left list or controls, right detail/editor |
| Data tables | History, Inbox, Stock Pool, Learning, Env | Horizontal scroll tables inside `.data-shell` |
| Progress timeline | Home, Inbox, History modal | Percent bar plus step cards, polled every 2.5s |
| Streaming terminal | Home, Inbox, Env | SSE text output in `.terminal` |
| Modal overlays | History | Artifact preview and run detail overlays |
| Tabs | Home reports, History run detail | Simple button tabs with active class |
| Markdown/report viewer | Home, History | Marked + DOMPurify for markdown, iframe for HTML reports |

### Styling Decisions Present

| Area | Current choice |
| --- | --- |
| Color mode | Dark-only via `color-scheme: dark` |
| Core colors | `#05070a`, `#0b0f12`, `#e9eff3`, `#98a6af`, teal `#25d6b5`, gold `#d1b56a`, amber `#c99b3f`, red `#f06f61`, green `#36d399` |
| Visual texture | Radial and grid backgrounds, multiple gradients, blurred sticky surfaces, panel shadows |
| Typography | Avenir Next / PingFang / Microsoft YaHei, mono for metrics and IDs, Songti serif in guide hero |
| Radius | 8 px global radius, 999 px pills, circular step indices |
| Density | Mixed: operational pages are dense, but hero/guide surfaces use large visual blocks |
| Responsive behavior | Desktop grid layouts collapse to single column below 900 px |
| Status encoding | Mostly color-coded pills: default, ok, warn, error |
| Known style bug | `.workflow-prompt-card.skipped` uses `var(--warn)`, but `--warn` is not defined |

### Interaction Flows Present

| Flow | Current implementation |
| --- | --- |
| Generate research tasks | Home button opens `/api/research-scan-stream` via `EventSource`, writes logs, creates run history, polls `/api/run-progress` |
| Fill Deep Research on home | Load `/api/deep-research/prompts`, select card, copy prompt, save answer to `/api/deep-research/fill`, or skip via `/api/deep-research/skip` |
| Fill Deep Research in full Inbox | Filter by date/status, row select, copy prompt, paste result, drag `.md/.markdown/.txt`, auto-match `PR-*`, save/skip |
| Rerun committee | Home or Inbox opens `/api/deep-research/rerun-stream`, tracks background run, polls progress |
| Single-agent dispatch | Home advanced panel opens `/api/agent-stream` for selected agent/date/type/no-llm |
| Read report | Home fetches `/api/report`, links to `/artifact/view`; History fetches `/api/artifact` and opens modal/iframe |
| Inspect run | History opens run detail modal, polls `/api/run-progress`, fetches `/api/run-llm-usage` |
| Edit stock pool | Stock Pool fetches `/api/stock-pool`, renders category tables, add/delete/collect rows, POST save |
| Review learning | Learning fetches `/api/learning`, can POST `/api/learning/refresh`, Timeline fetches `/api/learning/timeline/{ticker}` |
| Configure LLM | Env fetches/saves `/api/env`, checks `/api/llm/health`, checks or streams Codex login |
| Cleanup artifacts | Home advanced panel confirms and POSTs `/api/cleanup` |

## Benchmark Patterns

| Product | Source-backed pattern | Useful adaptation for ResearchOS |
| --- | --- | --- |
| LangSmith | Tracing projects expose Threads, Traces, and Runs tabs; clicking a row opens a side panel that keeps surrounding thread context visible. Source: [View traces](https://docs.langchain.com/langsmith/view-traces). | Replace modal-only run inspection with a persistent run detail drawer: run list on left, trace/step detail on right, report links pinned. |
| LangSmith | Prompt management includes prompt details, versions/environments, access controls, and Playground execution. Source: [Manage prompts](https://docs.langchain.com/langsmith/manage-prompts). | Treat Deep Research prompts as first-class objects with status, source signal, version/result history, and reusable actions. |
| LangSmith | Evaluators and datasets form a measurement layer for experiments and online/offline evaluation. Source: [Evaluation concepts](https://docs.langchain.com/langsmith/evaluation-concepts). | Extend Review Library into a decision-evaluation workspace instead of a passive metrics page. |
| Dify | Workflow Run History separates Result, Detail, and Tracing, including node order, timing, and bottlenecks. Source: [Run History](https://docs.dify.ai/en/guides/workflow/debug-and-preview/history-and-logs). | Standardize every run detail around Summary, Steps/Trace, Artifacts, Cost, and Failures. |
| Dify | Logs console shows conversation timeline, message details, performance data, feedback, and annotations. Source: [Logs](https://docs.dify.ai/en/use-dify/monitor/logs). | Add analyst notes, human decision notes, and feedback fields to report/run review surfaces. |
| Flowise | Product surfaces include visual builders, tracing and analytics, human-in-the-loop, templates, and reusable components. Source: [Flowise introduction](https://docs.flowiseai.com/). | Do not rebuild a full graph editor immediately, but add a compact read-only workflow map and step-level trace cards. |
| Flowise | Analytics/tracing can be enabled and used for Agentflow visibility. Source: [Flowise analytics](https://docs.flowiseai.com/using-flowise/analytics). | Make run instrumentation visible as a trace timeline with elapsed time, logs, artifacts, and status per agent. |

## Current State Audit

The first 10 rows are the top 10 critical UX problems to address before broader redesign work. Additional rows capture important secondary surfaces that still need design coverage.

| Component | Problem | Severity | Fix |
| --- | --- | --- | --- |
| Overall frontend architecture | `webui.py` mixes API routes, command streaming, data shaping, status logic, env logic, cleanup, and UI data contracts; templates contain large inline CSS and JS blocks. | Critical | Keep FastAPI backend, but split route groups, extract static CSS/JS, and define typed UI response contracts before any framework migration. |
| Home / Task Flow | The homepage contains launch flow, prompt fill, ops dashboard, report preview, single-agent debug, and destructive cleanup. The primary 1-2-3 flow competes with admin/debug controls. | Critical | Recast home as an Operations Dashboard with one primary run CTA, active run state, queue gate, and latest outputs; move single-agent/debug/cleanup into Settings or Admin. |
| Information architecture | Navigation is page-based but not workflow-based; run monitoring, report review, and cost detail are split across home and history. | High | Create grouped nav: Operate, Research, Reports, Review, Configure. Make Runs/Reports the canonical inspection surface. |
| Status model | Status classes and labels are duplicated in every template. `pending_cold_start` and `skip_cold_start` are handled in Inbox but not fully in the home gate. `var(--warn)` is undefined. | High | Add a shared status taxonomy and token map: idle, loading, queued, running, blocked, success, warning, error, cancelled, empty. Fix `--warn` or replace with `--amber`. |
| Run observability | Streaming terminal logs are visually dominant but hard to scan. Progress cards are useful, but trace, artifacts, errors, cost, and logs are not unified. | High | Build a run detail pattern with Summary, Trace, Logs, Artifacts, Cost, and Failures tabs or drawer sections. |
| Deep Research Inbox | Prompt table and detail editor work, but task priority, cold-start grouping, result history, knowledge receipt, and next action are visually underpowered. | High | Use a queue-master layout: filter rail, grouped prompt list, detail panel, result editor, and fixed action bar. Add explicit empty/blocked/dirty states. |
| Tables | Tables lack sorting, column visibility, sticky headers, row density controls, bulk actions, and persistent filters. Horizontal scroll works but hides context. | High | Adopt a table component spec now; in Phase 3 use TanStack Table. Phase 1 can add sticky headers, compact row styles, filters, and empty-state rows. |
| Forms and actions | Async actions rarely disable buttons while running; some save/copy/skip actions only update pills, not structured feedback. Destructive cleanup is buried in home. | High | Add button loading/disabled states, inline validation, dirty-state tracking, and a proper confirmation modal for destructive operations. |
| Accessibility | Dark-only, status mostly color-coded, few ARIA labels, incomplete tab semantics, modal focus not trapped, no visible skip/focus strategy beyond browser defaults. | High | Add semantic roles, focus management, keyboard-accessible tabs/modals, non-color status labels, contrast checks, and optional light mode. |
| Visual hierarchy | Operational pages use large hero/guide styling and decorative gradients that reduce scan efficiency for power users. | Medium | Shift to a quieter command-center layout: tighter headers, denser toolbars, fewer decorative gradients, clearer data hierarchy. |
| Report review | Reports open as link cards or iframe modals, but there is no integrated evidence summary, decision checklist, compare view, or analyst annotation. | Medium | Make report detail a first-class workspace with artifact preview, run trace, cost, checklist, risk flags, and notes. |
| Stock Pool | Inline editing is fast but lacks validation, dirty state, import/export, ticker duplicate warnings, and save conflict feedback. | Medium | Add dirty badges, duplicate detection, validation messages, staged changes, and clear category counts. |
| Review Library | Good metrics exist, but the page does not yet support investigation workflows such as filter by ticker/verdict/outcome or linking back to originating runs. | Medium | Turn it into an evaluation workspace with filters, timeline links, run/report provenance, and outcome status drilldown. |
| Guide | Product explanation is rich, but it uses the same operational visual language and occupies nav space equal to core work pages. | Low | Keep Guide, but make it secondary under Help. Remove decorative visual weight from daily operations. |

## Risk Corrections To The Roadmap

The original plan should not be read as a low-risk cosmetic cleanup. Four risks need to be handled explicitly before execution.

| Risk | Why it matters | Plan correction |
| --- | --- | --- |
| Phase 1 timeline was too optimistic | `base.html` alone is 2106 lines, and operational JS is embedded across templates. Fixing status tokens, pending cold-start states, async button states, and tests requires cross-template verification. | Phase 1 becomes 1.5-2 weeks. A separate 1-3 day "Phase 0" can handle only the safest defects: `--warn`, obvious status copy, and a no-contract-break audit. |
| Phase 3 migration trigger was too subjective | "Move when Jinja feels brittle" is not a decision rule. It can lead to premature migration or endless delay. | Add quantitative migration gates: partial count, JS module size, shared drawer count, advanced table count, and duplicated state-machine count. |
| Data/service migration risk was understated | `webui.py` is not just route rendering. It launches subprocesses, writes files, mutates `.env`, touches SQLite, reconciles stale runs, and deletes artifacts. Splitting route groups is also service extraction; the route split is service extraction work, not just file organization. | Phase 2 must include a service-boundary audit and service extraction plan before UI component refactoring. Routes should delegate to run, research, artifact, stock-pool, settings, and learning services. |
| SSE standardization was placed too late | Dashboard, Inbox rerun, agent stream, and Codex login already use separate EventSource clients. Reusable Active Run and trace components cannot be built safely without a shared event contract. | Move SSE inventory and event-contract normalization to Phase 1 end / Phase 2 start. Phase 3 typed SSE client becomes a React implementation of a contract already stabilized in Phase 2. |

### Data Layer Migration Risk Assessment

| Current route-layer behavior | Evidence in current code | Migration risk | Mitigation |
| --- | --- | --- | --- |
| Subprocess orchestration is embedded in route-adjacent helpers | `stream_command`, `stream_background_command_start`, `run_background_command_sequence`, and Codex login start processes directly | Route split can accidentally change run locking, cancellation, stdout capture, or background task ownership | Extract a `RunExecutionService` behind the existing API first; keep endpoint payloads unchanged until tests cover lifecycle states |
| Data writes happen directly from Web UI endpoints | Stock pool save, Deep Research fill/skip, `.env` save, log writes, cleanup deletes | UI refactor may become a data mutation refactor and introduce artifact corruption | Move writes into narrow service functions with input/output contracts; add tests for path constraints and preserved keys |
| SQLite reads and mutations are mixed with shape functions | Run history, cleanup history, progress rows, knowledge overview use direct SQLite access | Data access changes can break history, progress, learning, and cost pages at once | Add repository-style helpers for run log, knowledge, and learning queries before moving templates |
| Cleanup is destructive | `/api/cleanup` removes date-scoped directories and run history rows | Moving admin controls without guardrails can expose destructive actions too prominently | Keep cleanup in Admin/Settings, require confirmation, and test date scoping |
| Report rendering is both API and presentation logic | `/api/report`, `/api/artifact`, `/artifact/view`, humanized investment copy, report HTML renderer | Next frontend migration may duplicate report transformation or lose safety wording | Keep report transformation in FastAPI; frontend should request already-safe report display payloads |

Service extraction should be treated as backend work, not visual cleanup. A conservative Phase 2 sequence is: inventory side effects, wrap services, lock tests, then refactor templates.

## Design System Spec

### Design Principles

- Dense but legible: optimize for scanning, comparing, and repeated daily use.
- Status-first: every run, prompt, artifact, and setting should expose current state, next action, and blocking reason.
- Traceable decisions: every report should connect back to agents, prompts, evidence, cost, and risk flags.
- Quiet professional tone: financial intelligence workspace, not consumer SaaS landing page.
- Human boundary visible: avoid any UI language that implies auto-trading or final investment advice.

### Typography

| Token | Size / line | Use |
| --- | --- | --- |
| `text-xs` | 12 / 16 | Pills, metadata, table secondary text |
| `text-sm` | 13 / 18 | Dense table cells, form help |
| `text-base` | 14 / 20 | Default UI text |
| `text-md` | 16 / 22 | Panel titles, primary labels |
| `text-lg` | 18 / 24 | Page section headers |
| `text-xl` | 22 / 28 | Page titles |
| `text-display` | 28 / 34 | Only dashboard top title, not cards |

Recommended font stack: `Inter`, `Avenir Next`, `PingFang SC`, `Microsoft YaHei`, system sans-serif. Keep `SFMono-Regular`, `Menlo`, `Consolas`, monospace for run IDs, costs, logs, token counts, and tickers.

### Color Tokens

Keep dark mode as default, but add light mode tokens so reports, tables, and settings can be read in normal office lighting.

| Role | Dark | Light | Use |
| --- | --- | --- | --- |
| Background | `#090b0f` | `#f7f8fa` | App base |
| Surface | `#11161c` | `#ffffff` | Panels, cards, modals |
| Surface raised | `#171d25` | `#f1f4f7` | Drawers, sticky headers |
| Border | `#2a3340` | `#d8dee6` | Panel/table/input borders |
| Text | `#eef2f5` | `#16202a` | Primary text |
| Muted | `#9aa7b2` | `#667481` | Secondary text |
| Accent | `#19b89f` | `#087e70` | Primary actions, active nav |
| Info | `#5aa7ff` | `#1d6fd6` | Links, neutral highlights |
| Warning | `#d4a33f` | `#a76800` | Pending, running, needs attention |
| Danger | `#ef6f61` | `#c93a2d` | Failed/destructive |
| Success | `#36c98b` | `#168657` | Completed/saved |

Reduce decorative gradients to page-level accents only. Do not use color alone for status; pair all status colors with labels and icons.

### Spacing And Radius

| Token | Value | Use |
| --- | --- | --- |
| `space-1` | 4 px | Icon/text gap, compact metadata |
| `space-2` | 8 px | Pills, table cell inner rhythm |
| `space-3` | 12 px | Control gaps, row padding |
| `space-4` | 16 px | Panel padding, form groups |
| `space-5` | 20 px | Dense page section gap |
| `space-6` | 24 px | Page shell padding |
| `space-8` | 32 px | Major page breaks |
| `radius-sm` | 4 px | Inputs, table controls |
| `radius-md` | 8 px | Panels, cards, modals |
| `radius-pill` | 999 px | Status badges only |

### Component Library Recommendation

Phase 1 and Phase 2 should stay in FastAPI/Jinja for speed. If Phase 3 migration is approved, use:

- Next.js App Router with TypeScript.
- shadcn/ui on Radix primitives for accessible dialogs, tabs, select, popover, tooltip, drawer, command palette, toast, and form controls.
- Tailwind CSS for tokenized styling.
- TanStack Table for history, prompt queue, stock pool, and review tables.
- TanStack Query for fetch/cache/mutation state.
- Zustand or React context for lightweight UI state.
- Lucide React icons for status and actions.
- Recharts or Tremor only for small cost/outcome charts; avoid dashboard-chart overload.
- FastAPI remains the backend and owns command execution, SSE, persistence, validators, and report rendering.

## Redesigned Information Architecture

### Navigation Model

| Group | Page | Purpose |
| --- | --- | --- |
| Operate | Dashboard | Today's queue, active run, next action, latest output |
| Operate | Runs | Run history, active run monitor, trace, logs, artifacts, cost |
| Research | Deep Research Inbox | Prompt queue, result fill/skip, knowledge capture |
| Research | Stock Pool | Universe editing, validation, import/export |
| Review | Reports | Opportunity Memo and Risk Audit reading workspace |
| Review | Learning | Decision cases, outcomes, ticker timelines, monthly review |
| Configure | Settings | LLM provider, Codex login, health checks |
| Help | Guide | Workflow guide, safety boundaries, sample reports |

### Page Architecture

| Page | Recommended panels |
| --- | --- |
| Dashboard | Command bar, active run card, Deep Research gate summary, latest artifacts, queue health, system health |
| Runs | Run table, detail drawer, trace timeline, logs, artifacts, cost, failure diagnosis |
| Deep Research Inbox | Filter rail, grouped prompt list, detail/editor, knowledge receipt, fixed action bar |
| Reports | Report list, report reader, evidence/run sidebar, risk flags, human checklist, notes |
| Stock Pool | Category tabs, editable table, validation summary, staged changes, save/revert bar |
| Learning | KPI strip, filters, decision cases table, ticker timeline preview, outcome snapshots, monthly review |
| Settings | Provider card, secrets form, Codex status, LLM health test, diagnostics log |
| Guide | Static docs, sample reports, product boundaries |

### Key User Flows

#### Agent Launch

1. User lands on Dashboard.
2. Command bar shows date, run mode, LLM mode, and one primary action.
3. Preflight card confirms stock pool count, LLM provider health, pending Deep Research count, and whether rerun is blocked.
4. User starts research scan or committee rerun.
5. UI transitions to active run state with trace timeline and background-safe navigation.

#### Monitoring

1. Active run appears in Dashboard and Runs.
2. Step timeline shows Research, Deep Research gate, Value, Momentum, Quality, CIO, Risk, Notify.
3. Each step exposes state, elapsed time, estimate, attempts, logs, output artifacts, and failure reason.
4. Terminal logs remain available but collapsed by default.
5. Completion pins next action: fill prompts, read report, inspect failure, or open cost.

#### Result Review

1. User opens completed run or report.
2. Report workspace shows Opportunity Memo and Risk Audit with source run context.
3. Sidebar shows run status, agent steps, prompt fill coverage, cost, risk budget, fatal flaws, and open questions.
4. User can add a human note or mark follow-up questions for the Review Library.
5. Learning page later connects outcomes back to this run/report.

## Component Inventory For Redesign

| Component | Purpose | Required states |
| --- | --- | --- |
| App shell | Sidebar, top context, responsive page container | desktop, mobile, collapsed nav |
| Grouped sidebar nav | Operate/Research/Review/Configure/Help navigation | active, hover, disabled, mobile overflow |
| Command bar | Date/run mode/LLM mode and primary action | idle, preflight loading, ready, blocked, running |
| Status badge | Unified status display | idle, loading, queued, running, blocked, success, warning, error, cancelled, empty |
| Metric cell | Compact KPI readout | loading, zero, normal, warning, error |
| Panel | Reusable dense content frame | default, raised, warning, error, empty |
| Data table | History, prompts, stock pool, cases, costs | loading, empty, sorted, filtered, selected, error |
| Run trace timeline | Agent step visualization | pending, running, completed, failed, cancelled, skipped, retrying |
| Log viewer | Streaming or archived logs | empty, streaming, paused, error, searchable |
| Prompt queue item | Deep Research task row/card | pending, pending cold start, filled, skipped, selected, stale result ignored |
| Prompt detail panel | Prompt markdown, metadata, source signal, action controls | no selection, loading, dirty, save success, save error |
| Text editor area | Deep Research answer input | empty, dirty, validating, saving, saved, error, readonly |
| Drop zone | Import research result files | idle, drag over, unsupported file, matched prompt, unmatched prompt |
| Knowledge receipt | Saved result/knowledge entry summary | waiting, saved, skipped, extraction partial, error |
| Report reader | HTML/markdown artifact viewer | loading, missing, markdown, html iframe, error |
| Run detail drawer/modal | Inspect run without leaving list | loading, active, completed, failed, no data |
| Tabs | Report/progress/logs/cost sections | active, inactive, disabled, keyboard focus |
| Cost summary | Token/cost rollup | loading, estimated, exact, unavailable, error |
| Stock pool editor | Category and ticker editing | clean, dirty, invalid, saving, saved, conflict |
| Settings form | LLM provider, model, key, Codex login | pristine, dirty, saving, saved, failed, health checking |
| Confirmation dialog | Destructive cleanup and risky actions | closed, open, confirming, completed, failed |
| Toast/inline alert | Short feedback | info, success, warning, error |
| Empty state | No rows/no prompts/no reports | first-run, filtered empty, missing data, blocked |
| Help callout | Product boundary or workflow guidance | informational, warning |

## Interaction Patterns

### Real-Time Streaming Output

- Use SSE for command lifecycle events: `start`, `status`, `log`, `error`, `done`, but do not wait until Phase 3 to standardize the event shape.
- Phase 1 end / Phase 2 start should define a shared event contract used by research scan, committee rerun, single-agent stream, and Codex login stream.
- Display a compact run card first; keep raw terminal logs in a collapsible panel.
- Preserve background run continuity by showing active runs across Dashboard, Runs, and Inbox.
- Stop polling automatically on terminal states: completed, failed, partial_success, cancelled.

Recommended SSE event payload shape:

| Event | Required fields | Optional fields |
| --- | --- | --- |
| `start` | `status`, `message`, `command_label` | `run_id`, `step`, `index`, `total` |
| `status` | `status`, `message` | `run_id`, `step`, `next_action`, `severity` |
| `log` | `line` | `run_id`, `step`, `stream`, `timestamp` |
| `error` | `status`, `message` | `run_id`, `step`, `detail`, `next_action` |
| `done` | `status`, `return_code` | `run_id`, `history_path`, `artifact_links`, `next_action` |

The existing backend can keep emitting old fields during transition, but frontend helpers should normalize each event into this shape before components consume it.

### Agent Status Visualization

- Use a left-to-right or top-to-bottom trace timeline instead of freeform logs as the primary status view.
- Step card fields: label, agent, state, started, elapsed, estimate, attempts, exit code, artifact count, error summary.
- Status order: pending -> queued -> running -> completed or failed/cancelled/skipped.
- If a run is blocked by pending Deep Research, show the blocker as a gate, not a generic warning pill.

### Agent Configuration Inputs

- Put date, brief type, LLM mode, and run type in a persistent command bar.
- Use segmented controls for brief type and LLM mode; use date input for date; use select only for long option sets like agent name.
- Disable primary actions while their async request is active.
- Show preflight warnings before long runs: missing `.env`, no stock pool, pending prompts, active run lock.
- Move admin-only single-agent dispatch into a separate Advanced Run page or Settings panel.

### Feedback States

- Every mutation should show three layers: button loading state, inline result, and toast/log entry.
- Empty states must tell the user the next valid action.
- Error states must include cause, affected object, and next action.
- Success states must link to the created or updated object: run ID, result path, report path, knowledge entry, or stock pool path.

## Phased Implementation Roadmap

Each phase includes concrete file-level tasks so the plan can be converted directly into implementation tickets.

### Phase 0: Safety Patch, 1-3 days

Goal: Fix the safest visible defects before larger refactoring starts.

| File | Task |
| --- | --- |
| `templates/base.html` | Replace or define the undefined warning token used by skipped prompt cards. |
| `templates/index.html` and `templates/deep_research.html` | Inventory every status value used by prompt and run views, including `pending_cold_start` and `skip_cold_start`. |
| `templates/*.html` | Inventory current EventSource consumers and document their emitted/consumed event fields before changing behavior. |
| `tests/test_webui_*.py` | Add focused tests only for known status mapping defects if current test structure allows it without large refactor. |

Deliverables:

- No undefined CSS token for warning/skipped states.
- Status and SSE inventory ready for Phase 1.
- No route or API contract changes.

### Phase 1: Stabilization, 1.5-2 weeks

Goal: Make the existing FastAPI/Jinja UI clearer, safer, and more consistent without changing core architecture.

| File | Task |
| --- | --- |
| `templates/base.html` | Normalize status tokens to consistent roles; reduce decorative gradients on operational pages; add light-mode token placeholders only where they do not force a full theme refactor. |
| `templates/base.html` | Add reusable utility classes for status badges, toolbar density, sticky table headers, empty states, and visually hidden text. |
| `templates/index.html` | Demote or collapse "single-agent dispatch" and cleanup into an Advanced section; make the 1-2-3 task flow the only primary action sequence. |
| `templates/index.html` | Handle `pending_cold_start` and `skip_cold_start` consistently in home queue counts and cards. |
| `templates/index.html` and `templates/deep_research.html` | Disable save/skip/rerun buttons during active requests; add dirty/empty validation messages before POSTs. |
| `templates/index.html`, `templates/deep_research.html`, `templates/env.html` | Introduce a shared SSE normalization helper for current streams without changing backend event names yet. |
| `templates/history.html` | Make run detail the canonical inspection surface by improving tab labels: Summary, Trace, Artifacts, Cost, Logs. Keep the modal for now. |
| `templates/stock_pool.html` | Add dirty-state status, duplicate ticker warning, unsaved-change warning, and clear category counts. |
| `templates/env.html` | Separate provider settings from diagnostics; add visible loading states for health checks and Codex login. |
| `webui.py` | Add lightweight shared status fields to API payloads where missing, without changing existing keys; do not move subprocess or data writes yet. |
| `tests/test_webui_*.py` | Add tests for status normalization edge cases: cold start, skipped cold start, missing reports, running progress, usage missing. |

Deliverables:

- Cleaner home hierarchy.
- Unified status language.
- A first shared SSE normalization layer for existing streams.
- Safer mutation feedback.
- No backend contract break.

### Phase 2: Service And Component Refactor, 3-5 weeks

Goal: Refactor the Jinja frontend into maintainable components and improve the main work surfaces. If service extraction is deferred and the work is strictly visual/static-asset extraction, this may fit 2-4 weeks; if route-layer side effects are cleaned up properly, plan for 3-5 weeks.

| File / area | Task |
| --- | --- |
| `webui.py` | First map side effects by domain: subprocess execution, RunLog/SQLite, file writes, cleanup deletes, report rendering, env writes. |
| Service modules | Extract route-adjacent logic into service modules before moving routes: `services/runs.py`, `services/research.py`, `services/artifacts.py`, `services/settings.py`, `services/stock_pool.py`, `services/learning.py`. |
| API route modules | After service wrappers exist, split route groups into modules such as `web_routes.py`, `api_runs.py`, `api_research.py`, `api_settings.py`, and `api_learning.py`; keep `webui.py` as app factory/entrypoint. |
| SSE contract | Make backend stream payloads conform to the shared event shape while preserving legacy fields for compatibility. |
| `templates/partials/` | Introduce Jinja partials or macros for panel, badge, metric strip, progress step, empty state, and toolbar. |
| `static/css/` | Move inline CSS out of `base.html` into `tokens.css`, `layout.css`, `components.css`, and `pages.css`. |
| `static/js/` | Move repeated helpers into `status.js`, `sse.js`, `run-progress.js`, `format.js`, and page-specific modules. |
| `templates/history.html` | Replace modal-first inspection with a split layout: runs table plus side detail drawer. |
| `templates/deep_research.html` | Convert prompt table into queue layout with grouped sections: Cold Start, Pending, Filled, Skipped, Ignored/Stale. |
| `templates/index.html` | Rebuild Dashboard around cards: Active Run, Deep Research Gate, Latest Artifacts, System Health, Queue Metrics. |
| `templates/learning.html` | Add filters by ticker, verdict/status, date, and outcome status; link each row back to run/report provenance. |
| `templates/stock_pool.html` | Add row-level validation, staged edits, save/revert action bar, import/export YAML actions if backend supports it. |
| API contracts | Return consistent `ui_status`, `label`, `severity`, `next_action`, and `links` fields for runs, prompts, reports, settings, and learning rows. |

Deliverables:

- Maintainable frontend assets.
- Service boundaries around route-layer side effects.
- Shared SSE contract used by active run and rerun views.
- Stronger run and prompt inspection.
- More useful tables without adopting a Node stack.
- Lower risk before any full rebuild.

### Phase 3: Full Rebuild, 4-8 weeks

Goal: Move to a modern frontend only if the product needs reusable complex interactions beyond Jinja's practical ceiling.

| Area | Task |
| --- | --- |
| `frontend/` | Create Next.js + TypeScript frontend with shadcn/ui, Radix, Tailwind, TanStack Query, TanStack Table, and Lucide icons. |
| `webui.py` / API modules | Keep FastAPI as backend. Expose stable JSON APIs under `/api/v1/*`; preserve old endpoints until migration completes. |
| SSE | Implement a typed React SSE client for run streams, Codex login streams, and background run resume against the Phase 2 event contract. |
| Runs UI | Build run table, drawer, trace timeline, logs viewer, artifacts panel, and cost panel. |
| Deep Research UI | Build queue, prompt detail, answer editor, file import, knowledge receipt, and rerun blocker logic. |
| Report UI | Build integrated report reader with evidence sidebar, risk flags, human checklist, and notes. |
| Stock Pool UI | Use TanStack Table for editable category tables, validation, dirty state, and keyboard workflows. |
| Testing | Add Playwright for core workflows and visual checks; keep backend pytest. |
| Deployment | Serve Next static build behind FastAPI or run a separate dev server in local mode; document both in `LOCAL_RUNBOOK.md`. |

Migration trigger:

Choose Phase 3 only when at least two of these thresholds are met after Phase 2:

- More than 20 Jinja partials/macros are required to keep page duplication under control.
- Any single extracted `static/js/*.js` module exceeds 500 lines after obvious helper extraction.
- Three or more reusable drawer/modal workflows are needed with shared focus management, async state, tabs, and resume behavior.
- Four or more tables require the full advanced table set: sorting, filtering, column visibility, persisted density, row selection, and bulk actions.
- The same client state machine for run/progress/prompt mutations is duplicated across three or more pages.
- Cross-page active-run resume requires shared client cache/state that becomes awkward in vanilla JS.

Do not migrate just for visual polish. The Python backend is already the right owner for orchestration, validation, file IO, local safety boundaries, report transformation, and data mutation.

## Tech Stack Recommendation

Recommended immediate stack: keep FastAPI + Jinja + vanilla JS for Phase 1 and Phase 2, but modularize aggressively. This maximizes solo-developer velocity because it avoids a Node toolchain while the UI model is still being clarified.

Recommended future stack: Next.js + TypeScript + shadcn/ui/Radix + TanStack Table/Query, backed by the existing FastAPI async APIs. This is warranted only after the quantified Phase 3 migration thresholds are met, not merely because a modern frontend would look cleaner.

Backend compatibility:

- FastAPI remains the source of truth for subprocess orchestration, SSE, run locks, SQLite reads, `.env` writes, report rendering, YAML persistence, and data safety.
- Frontend migration should not change business outputs under `data/`.
- Existing endpoints can be retained during migration; new `/api/v1` contracts should add structure rather than remove current fields.

## Acceptance Criteria For The Redesign

- A user can tell the current system state in under 10 seconds: active run, blocked gate, pending research, latest report, and provider health.
- A user can inspect any completed or failed run without leaving context: trace, logs, artifacts, cost, failure reason.
- Every mutation has loading, success, error, and empty states.
- Every status has a label, color, and non-color signal.
- Report review connects outputs to prompts, agents, risk flags, and human checklist.
- Stock Pool editing protects against accidental invalid saves.
- SSE is standardized before reusable active-run, rerun, and Codex-login components are built.
- Framework migration is gated by measurable complexity thresholds, not subjective discomfort with Jinja.
- The UI stays dense and calm, with fewer decorative surfaces and stronger hierarchy.
- No recommendation implies auto-trading or investment advice.
