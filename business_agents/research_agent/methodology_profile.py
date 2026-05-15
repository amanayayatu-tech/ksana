"""Executable profile derived from the frozen K deep research methodology."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RESEARCH_SYSTEM_METHODOLOGY_ID = "k_deep"
RESEARCH_SYSTEM_FRAMEWORK_ID = "k_deep_research_questions_v1"
RESEARCH_SYSTEM_SOURCE_FILE = "research_system_v0.3.md"
RESEARCH_SYSTEM_VERSION = "0.3"

RESEARCH_SYSTEM_HARD_RULES: dict[str, Any] = {
    "perplexity_integration_mode": "human_in_the_loop",
    "max_prompts_per_daily_brief": 30,
    "max_prompts_per_signal": 5,
    "routing_must_include_min_agents": 2,
    "no_trading_advice": True,
    "no_external_api_calls": True,
}

RESEARCH_OBJECT_TYPES = [
    "company",
    "industry",
    "market",
    "change",
    "investment_system",
    "human_nature",
    "special_event",
    "arbitrage",
    "beta_linked",
]

METHODOLOGY_PHILOSOPHY = [
    "深度研究不等于细节研究，选题是战略问题。",
    "变化比静态细节更重要；不信仰价值回归，只信仰事件导致的价值回归。",
    "宏观重大事件 > 行业重大事件 > 个股重大事件；事件越大市场越容易反应不足。",
]

SELF_CRITIQUE_HOOKS = [
    "是否把深度研究误作细节研究，堆了很多材料却没有主矛盾？",
    "是否因为长期研究某个标的而对它产生感情，忽略了证伪点？",
    "是否没有区分行业 beta、宏观 beta 和个股 alpha？",
    "是否过度依赖 bottom-up 连续性假设，忽略了非连续变化？",
    "是否在 Perplexity 未回填时把未验证证据当作高置信度事实？",
]

RESEARCH_GATES: list[dict[str, Any]] = [
    {
        "gate_id": "Gate 1",
        "rule_id": "research_object_definition",
        "label": "研究对象定义",
        "check_items": [
            "主研究对象必须落入 9 类研究对象之一。",
            "主研究对象只能有 1 个，辅助对象最多 2 个。",
            "必须说明研究对象和潜在收益来源的关系。",
        ],
        "questions": [
            "{display_name} 这次异动的主研究对象到底是公司、行业、市场、变化、特殊事件、套利，还是 beta linked？",
            "除主对象外，是否还需要同时研究行业、竞争格局或宏观市场作为辅助对象？请限制在 2 个以内。",
        ],
    },
    {
        "gate_id": "Gate 2",
        "rule_id": "great_idea_candidate",
        "label": "Great Idea 候选",
        "check_items": [
            "至少存在一个明确事件、变化或时间窗口。",
            "必须说明市场忽略了什么关键因素。",
            "区分未定价和严重定价错误。",
        ],
        "questions": [
            "触发规则 {trigger_rule_text} 背后，是否存在明确事件、时间窗口或市场未处理的关键因素？",
            "这次异动更像未定价、严重定价错误、还是市场已经完成重定价？请给出可验证依据。",
        ],
    },
    {
        "gate_id": "Gate 3",
        "rule_id": "discontinuity_detection",
        "label": "非连续变化 / 竞争格局",
        "check_items": [
            "变化必须足够大，能够导致市场先验概率重估。",
            "重点检查成本效率曲线、渗透率、供需结构、产品替代、商业模式链接方式。",
            "必须回答为什么是现在。",
        ],
        "questions": [
            "过去 90 天，行业需求、供给、渗透率、成本曲线、产品替代或商业模式是否发生非连续变化？",
            "主要竞争对手、替代品、平台规则或供应链伙伴是否出现会改变竞争格局的新动作？",
            "这次变化是否能改变销量、价格、利润率、份额、议价力或技术领先性？为什么发生在现在？",
        ],
    },
    {
        "gate_id": "Gate 4",
        "rule_id": "beta_and_attribution",
        "label": "Beta 与收益归因",
        "check_items": [
            "拆分企业基本面、估值、宏观 beta、行业 beta、个股 alpha。",
            "不能把行业 beta 误写成公司 alpha。",
            "如果无法区分 beta 和 alpha，必须生成研究问题而非结论。",
        ],
        "questions": [
            "这次价格反应中，企业 EPS/收入变化、估值变化、宏观 beta、行业 beta、个股 alpha 各自可能贡献多少？",
            "同行、指数、ETF 或同主题股票是否同步异动？如果同步，如何证明 {ticker} 有独立 alpha？",
        ],
    },
    {
        "gate_id": "Gate 5",
        "rule_id": "bayesian_update",
        "label": "贝叶斯更新",
        "check_items": [
            "必须区分市场先验、我方先验、事件后后验。",
            "必须判断市场是否已经做出贝叶斯调整。",
            "缺关键证据时保持 evidence_unverified。",
        ],
        "questions": [
            "异动前市场对 {display_name} 的核心先验是什么？新事件如何改变这个先验？",
            "当前价格是否已经反映后验概率调整？还有哪些事实调整或预期调整尚未完成？",
        ],
    },
    {
        "gate_id": "Gate 6",
        "rule_id": "workflow_routing",
        "label": "工作流分流",
        "check_items": [
            "先做是非题，再做数学题。",
            "判断是否值得投入深度研究资源。",
            "给出适合下游交易 Agent 的路由理由。",
        ],
        "questions": [
            "这条信号应保留为 daily_scan，升级为 special_attention，还是值得进入 deep_research？依据是什么？",
            "如果交给三位投资 Agent，F partner、W partner、G partner分别最可能围绕什么问题产生分歧？",
        ],
    },
    {
        "gate_id": "Gate 7",
        "rule_id": "research_signal_emission",
        "label": "Research Signal Emission",
        "check_items": [
            "发出信号前必须有证伪点。",
            "必须列出 Perplexity 已验证、未验证和被跳过的问题。",
            "不得输出任何交易层字段。",
        ],
        "questions": [
            "哪些公开证据最能证伪这次异动的主因？请列出可跟踪指标、来源链接和时间点。",
            "哪些问题仍未验证，必须由后续 Perplexity 回填或公司/行业公开数据继续确认？",
        ],
    },
]


class _SafeContext(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def build_methodology_profile_snapshot() -> dict[str, Any]:
    """Return a compact, serializable snapshot of the frozen methodology authority."""

    return {
        "methodology_id": RESEARCH_SYSTEM_METHODOLOGY_ID,
        "methodology_version": RESEARCH_SYSTEM_VERSION,
        "methodology_source": RESEARCH_SYSTEM_SOURCE_FILE,
        "framework": RESEARCH_SYSTEM_FRAMEWORK_ID,
        "hard_rules": dict(RESEARCH_SYSTEM_HARD_RULES),
        "research_object_types": list(RESEARCH_OBJECT_TYPES),
        "methodology_philosophy": list(METHODOLOGY_PHILOSOPHY),
        "gates_applied": [
            {
                "gate_id": gate["gate_id"],
                "rule_id": gate["rule_id"],
                "label": gate["label"],
            }
            for gate in RESEARCH_GATES
        ],
        "self_critique_hooks": list(SELF_CRITIQUE_HOOKS),
    }


def build_gate_question_groups(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Render deterministic Perplexity question groups from Gate 1-7."""

    safe_context = _SafeContext(context)
    groups: list[dict[str, Any]] = []
    for gate in RESEARCH_GATES:
        groups.append(
            {
                "gate_id": gate["gate_id"],
                "category": gate["rule_id"],
                "label": gate["label"],
                "check_items": list(gate["check_items"]),
                "questions": [question.format_map(safe_context) for question in gate["questions"]],
            }
        )
    return groups
