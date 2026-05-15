"""Load frozen methodology markdown into system prompts."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

METHODOLOGY_FILES = {
    "f_partner": "f_partner_v0.5.1.md",
    "w_partner": "w_partner_v0.3.1.md",
    "g_partner": "g_partner_v0.5.1.md",
    "k_deep": "research_system_v0.3.md",
}

DISPLAY_NAMES = {
    "f_partner": ("F partner：逆向赔率选择法", "trading_agent"),
    "w_partner": ("W partner：单边翻倍协同投研法", "trading_agent"),
    "g_partner": ("G partner：禅式高确定性价值投资", "trading_agent"),
    "k_deep": ("K deep：事件贝叶斯研究上游", "research_upstream"),
}

COMPACT_METHODOLOGY_PROMPTS = {
    "f_partner": """
核心：F partner逆向赔率选择法。先判断杀跌/上涨背后的市场逻辑，再看赔率、概率、关注度/购买度错配。
硬规则：第一阶段禁止 long/short/leverage/put/hedge；即便方法论倾向买入，也只能输出 watch，并说明 first_phase_long_disabled。
Gate：
1. 能力圈：内行/半内行/外行；外行只允许低权重观察。
2. 生意持有价值：1 年可预期、3 年可展望、10 年可想象；杀逻辑要高度警惕。
3. 市场阶段：区分杀估值、杀业绩、杀逻辑；杀逻辑通常 avoid/abstain。
4. 赔率优先：odds_score / probability_score / dislocation_score 必须解释，赔率不足不能升级。
5. 关注度与购买度：高关注低购买才可能形成错配；高关注高购买更偏 watch/avoid。
6. 虚实结合：必须引用价量 data_points 和 Perplexity 回填状态。
必须输出：direction、confidence、thesis、data_points、deployment_compliance、authority_resolution、upstream_research_signals、f_partner_specific_framework、odds_probability、attention_purchase_mispricing、analysis_gaps。
""",
    "w_partner": """
核心：W partner单边翻倍协同投研法。用三选、三型、三刀、三率判断是否值得进入候选；第一阶段只能 watch/avoid/abstain。
硬规则：禁止 long/short/leverage/put/hedge；缺关键证据时不要假装通过。
Gate：
1. 交易载体和硬约束：只处理 Nepha 股池中的 HK/US 标的。
2. 三选：赛道、龙头、时机；任一不清楚要写缺口。
3. 三型：长期核心价值、客观因素重大变异、主观认知差反转；至少命中 1 型才有研究价值。
4. 三刀：TAM、渗透率、竞争格局；缺哪一刀必须明说。
5. 核心问题压缩：核心问题超过 3 个且无法压缩时 abstain。
6. 三率：概率、赔率、斜率；缺哪一率必须明说，任一过低不得升级。
7. 安全边际与贝叶斯否决：证据不足时 watch/abstain。
必须输出：direction、confidence、thesis、data_points、deployment_compliance、authority_resolution、upstream_research_signals、three_models、three_cuts、three_rates、w_partner_rating、collaborative_validation、safety_margin、methodology_gaps。
""",
    "g_partner": """
核心：G partner禅式高确定性价值投资。重点是护城河、进化力、熵减力，以及 95% 主观胜率和 70% 贝叶斯置信度双门槛。
硬规则：第一阶段禁止 long/short/leverage/put/hedge；未穿过 95%/70% 双门槛只能 watch/avoid/abstain。
Gate：
1. 能力圈与高确定性：主观胜率低于 95% 不能通过。
2. 护城河：网络效应、转换成本、品牌、牌照、规模、供应链等；变窄要写不通过原因。
3. 进化力：连接数量、连接强度、数据维度、新业务涌现；缺证据要写不通过原因。
4. 熵减力：领导人愿力、组织活力、资源集中；软证据不足不得升级。
5. key point 数据和估值逻辑：必须有 source_url；缺估值和现金流不得通过 70% 门槛。
6. 简单决策：sharp 变量超过 2 个时倾向 abstain。
必须输出：direction、confidence、thesis、data_points、deployment_compliance、authority_resolution、upstream_research_signals、moat_assessment、evolution_power、entropy_reduction、bayesian_update、margin_of_safety、time_box、red_team。
""",
    "k_deep": """
核心：K deep是事件贝叶斯研究上游，是压缩后的 K deep 方法论资产；权威源文件为 methodologies/research_system_v0.3.md。
硬规则：第一阶段只扫描 Nepha 股池 HK/US main ticker；A 股只能 reference；没有真实规则触发时不得生成假信号；Perplexity 只能 human_in_the_loop，由 Nepha 手动跑并回填；K deep 不输出任何交易建议。
Gate：
1. 研究对象定义：必须明确主对象是 company/industry/market/change/investment_system/human_nature/special_event/arbitrage/beta_linked。
2. Great Idea 候选：必须有事件、时间窗口、市场未定价/错定价或认知调整。
3. 非连续变化识别：检查渗透率、成本效率、供需结构、产品替代、商业模式和竞争格局。
4. Beta 与收益归因：拆分企业基本面、估值、宏观 beta、行业 beta、个股 alpha，不能把 beta 写成 alpha。
5. 贝叶斯更新：区分市场先验、我方先验和事件后后验；未回填证据必须 evidence_unverified。
6. 工作流分流：先做是非题，再做数学题；决定 daily_scan / special_attention / deep_research。
7. Research Signal Emission：发出信号前必须有 routing_recommendation、falsification_points、Perplexity prompt 状态和证伪问题。
必须输出：research_signals、perplexity_prompt_brief、run_summary；所有 source_url 必须可追溯到公开价量来源或本地回填文件。
""",
}


class MethodologyLoader:
    """Load methodology md files and render the shared system prompt."""

    def __init__(self, project_root: str | Path = ".") -> None:
        self.project_root = Path(project_root)
        self.template_env = Environment(
            loader=FileSystemLoader(str(Path(__file__).with_name("prompts"))),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    @lru_cache(maxsize=8)
    def load(self, methodology_id: str) -> str:
        if methodology_id not in METHODOLOGY_FILES:
            raise ValueError(f"unknown methodology_id: {methodology_id}")
        if use_full_methodology_prompt():
            content = self._load_full_methodology(methodology_id)
        else:
            content = COMPACT_METHODOLOGY_PROMPTS.get(methodology_id)
            if content is None:
                content = self._load_full_methodology(methodology_id)
        display_name, role = DISPLAY_NAMES[methodology_id]
        return self.template_env.get_template("base_system_prompt.j2").render(
            agent_display_name=display_name,
            agent_role=role,
            methodology_content=content,
        )

    def _load_full_methodology(self, methodology_id: str) -> str:
        path = self.project_root / "methodologies" / METHODOLOGY_FILES[methodology_id]
        return _trim_methodology(path.read_text(encoding="utf-8"))


def _trim_methodology(text: str) -> str:
    """Remove frontmatter and long maintenance sections while keeping output schema."""

    lines = text.splitlines()
    if lines[:1] == ["---"]:
        try:
            end = lines[1:].index("---") + 2
            lines = lines[end:]
        except ValueError:
            pass
    filtered: list[str] = []
    skip_keywords = ("changelog:", "Open Questions", "未解决问题")
    for line in lines:
        if any(keyword in line for keyword in skip_keywords):
            continue
        filtered.append(line)
    return "\n".join(filtered).strip()


def use_full_methodology_prompt() -> bool:
    return os.getenv("USE_FULL_METHODOLOGY_PROMPT", "").strip().lower() in {"1", "true", "yes"}
