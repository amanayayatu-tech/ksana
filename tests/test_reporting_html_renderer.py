from __future__ import annotations

from orchestrator.reporting.html_renderer import (
    ReportPresentation,
    markdown_to_html,
    render_report_html,
    split_summary_item,
)


def test_markdown_table_preserves_escaped_pipe_in_cell():
    markdown = "\n".join(
        [
            "| 字段 | 解释 |",
            "| --- | --- |",
            r"| thesis | cash flow \| margin spread |",
        ]
    )

    rendered = markdown_to_html(markdown)

    assert "<td>cash flow | margin spread</td>" in rendered
    assert rendered.count("<td>") == 2


def test_inline_links_allow_only_safe_protocols():
    rendered = markdown_to_html(
        "\n".join(
            [
                "[source](https://example.com/report?a=1&b=2)",
                "[mail](mailto:research@example.com)",
                "[jump](#section-1)",
                "[bad](javascript:alert(1))",
            ]
        )
    )

    source_link = (
        '<a href="https://example.com/report?a=1&amp;b=2" '
        'target="_blank" rel="noopener noreferrer">source</a>'
    )
    mail_link = '<a href="mailto:research@example.com" target="_blank" rel="noopener noreferrer">mail</a>'
    anchor_link = '<a href="#section-1">jump</a>'

    assert source_link in rendered
    assert mail_link in rendered
    assert anchor_link in rendered
    assert "javascript:" not in rendered
    assert "bad" in rendered


def test_summary_item_compacts_long_technical_values():
    label, value = split_summary_item(
        "未验证 ID：R-WP-20260515-AMD, R-WP-20260515-BABA, R-WP-20260515-MU, R-WP-20260515-NVDA"
    )

    assert label == "未验证 ID"
    assert value.endswith("...")
    assert len(value) <= 75


def test_report_html_adds_editorial_digest_and_keeps_full_evidence():
    markdown = "\n".join(
        [
            "# Red Team Audit — AUDIT-20260516-AM",
            "",
            "## 📋 执行摘要",
            "- 审计建议总数：**12**",
            "- ⚠️ 系统级风险：4 条",
            "",
            "## 🎯 方法论挑刺",
            "**建议 Chairman 二次裁决**：wait（required=True）",
            "- 推翻本次裁决的条件：Deep Research 无法交叉验证。",
            "",
            "## 📎 附录",
            "- data/red_team_audits/20260516/AUDIT-20260516-AM.md",
        ]
    )

    rendered = render_report_html(
        markdown,
        ReportPresentation(
            title="AUDIT-20260516-AM",
            report_label="Risk Audit",
            eyebrow="RESEARCHOS REPORT VIEW",
        ),
    )

    assert "editorial-digest" in rendered
    assert "三条线读完这份报告" in rendered
    assert "report-disclosure" in rendered
    assert "Risk Audit" in rendered
    assert "CIO Agent" in rendered
    assert "Deep Research 无法交叉验证" in rendered
    assert "Red Team Audit" not in rendered
    assert "Chairman" not in rendered
    assert "📋" not in rendered
    assert "🎯" not in rendered
    assert "📎" not in rendered
    assert "data/red_team_audits" not in rendered


def test_editorial_digest_prefers_decision_lines_over_low_signal_fields():
    markdown = "\n".join(
        [
            "# IC Brief — BRIEF-20260516-AM",
            "",
            "## 执行摘要",
            "- 分歧建议：0 条",
            "",
            "## 每条建议详情",
            "**一致度**：other",
            "**CIO 裁决**：补充研究",
            "- 三位 Agent 当前分布为 Value Partner:观察, Quality Partner:暂不判断。",
            "**未关闭问题**：",
            "- 仍有 8 个未关闭问题，优先关注：编号 | 问题 | 跟踪来源 | 时间节点",
        ]
    )

    rendered = render_report_html(
        markdown,
        ReportPresentation(
            title="BRIEF-20260516-AM",
            report_label="IC Brief",
            eyebrow="RESEARCHOS REPORT VIEW",
        ),
    )

    assert "CIO 裁决：补充研究" in rendered
    assert "三位 Agent 当前分布" in rendered
    assert "仍有 8 个未关闭问题，优先关注：见正文清单" in rendered
    assert "一致度: other" not in rendered


def test_editorial_digest_prefers_opportunity_memo_status():
    markdown = "\n".join(
        [
            "# Opportunity Memo — BRIEF-20260516-AM",
            "",
            "## 每条建议详情",
            "- **Opportunity Score**：82/100",
            "- **机会状态**：需人工拍板",
            "- **action_route**：`human_override_required`",
            "- 分歧建议：0 条",
        ]
    )

    rendered = render_report_html(
        markdown,
        ReportPresentation(
            title="BRIEF-20260516-AM",
            report_label="Opportunity Memo",
            eyebrow="RESEARCHOS REPORT VIEW",
        ),
    )

    assert "Opportunity Score" in rendered
    assert "82/100" in rendered
    assert "机会状态" in rendered
    assert "需人工拍板" in rendered
    assert "核心判断" in rendered


def test_report_html_keeps_why_market_might_be_wrong():
    markdown = "\n".join(
        [
            "# Opportunity Memo — BRIEF-20260516-AM",
            "",
            "## 每条建议详情",
            "#### Opportunity Memo",
            "- **市场共识视角**：市场认为增长已经充分定价。",
            "- **非共识 thesis**：系统认为 AI 催化仍被低估。",
            "**市场可能错在哪里**：",
            "- 市场可能低估了 AI 催化兑现速度。",
        ]
    )

    rendered = render_report_html(
        markdown,
        ReportPresentation(
            title="BRIEF-20260516-AM",
            report_label="Opportunity Memo",
            eyebrow="RESEARCHOS REPORT VIEW",
        ),
    )

    assert "市场可能错在哪里" in rendered
    assert "市场可能低估了 AI 催化兑现速度" in rendered
