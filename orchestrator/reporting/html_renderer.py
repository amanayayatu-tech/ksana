"""Single-file HTML presentation renderer for generated reports."""

from __future__ import annotations

from dataclasses import dataclass
import html
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ReportPresentation:
    """Metadata used to frame a readable report HTML file."""

    title: str
    report_label: str
    eyebrow: str
    source_path: str = ""


@dataclass(frozen=True)
class ReportDigestCard:
    label: str
    value: str
    note: str
    tone: str = "neutral"


@dataclass(frozen=True)
class ReadingPanel:
    label: str
    title: str
    body: str


def render_report_html(markdown: str, presentation: ReportPresentation) -> str:
    """Render a Markdown report as a polished, self-contained HTML document."""

    markdown = productize_report_text(markdown)
    title = extract_title(markdown) or presentation.title or "投研报告"
    title = productize_report_text(title)
    display_title, title_detail = split_title_detail(title)
    sections = extract_h2_sections(markdown)
    summary_items = extract_summary_items(sections)
    toc_items = [(section.anchor, section.title) for section in sections]
    body_html = arrange_report_sections(markdown_to_html(markdown))
    digest_cards = build_digest_cards(markdown, summary_items)
    summary_html = render_summary_grid(digest_cards)
    editorial_html = render_editorial_digest(build_reading_panels(markdown, summary_items))
    toc_html = render_toc(toc_items)
    source_html = (
        f'<span class="meta-chip">报告中心 · {html.escape(basename_display(presentation.source_path))}</span>'
        if presentation.source_path
        else ""
    )
    detail_html = (
        f'<span class="meta-chip report-id">{html.escape(title_detail)}</span>' if title_detail else ""
    )

    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="zh-CN">',
            "<head>",
            '  <meta charset="utf-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1">',
            f"  <title>{html.escape(title)}</title>",
            f"  <style>{REPORT_CSS}</style>",
            "</head>",
            "<body>",
            '  <div class="report-frame">',
            '    <aside class="report-rail" aria-label="报告导航">',
            f'      <div class="rail-mark">{html.escape(presentation.report_label)}</div>',
            f'      <div class="rail-title">{html.escape(short_title(title))}</div>',
            f"      {toc_html}",
            "    </aside>",
            '    <main class="report-page">',
            '      <section class="report-hero">',
            '        <div class="hero-grid">',
            "          <div>",
            f'            <div class="eyebrow">{html.escape(presentation.eyebrow)}</div>',
            f"            <h1>{html.escape(display_title)}</h1>",
            '            <div class="meta-row">',
            f'              <span class="meta-chip">{html.escape(presentation.report_label)}</span>',
            f"              {detail_html}",
            f"              {source_html}",
            "            </div>",
            "          </div>",
            '          <div class="hero-note">',
            "            <strong>阅读方式</strong>",
            "            <span>先看上方 briefing board，再看三条阅读线索；正文保留完整证据，附录默认折叠。</span>",
            "          </div>",
            "        </div>",
            f"        {summary_html}",
            "      </section>",
            f"      {editorial_html}",
            f"      {toc_html.replace('toc rail-toc', 'toc page-toc')}",
            f'      <article class="report-content">{body_html}</article>',
            "    </main>",
            "  </div>",
            "</body>",
            "</html>",
            "",
        ]
    )


@dataclass(frozen=True)
class MarkdownSection:
    title: str
    anchor: str
    lines: list[str]


def extract_title(markdown: str) -> str:
    for line in markdown.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return clean_markdown_text(match.group(1))
    return ""


def short_title(title: str) -> str:
    cleaned = productize_report_text(title)
    cleaned = cleaned.replace("投研委员会简报", "Opportunity Memo").replace("Risk Audit Audit", "Risk Audit")
    return cleaned[:44] + ("..." if len(cleaned) > 44 else "")


def basename_display(path: str) -> str:
    normalized = path.replace("\\", "/")
    return normalized.rsplit("/", 1)[-1] if normalized else path


def productize_report_text(text: str) -> str:
    """Replace internal role names and runtime paths in presentation HTML."""

    replacements = [
        ("Nepha AI IC", "WorldPay IC"),
        ("AI Native 投资公司", "AI Native 投研工作流"),
        ("投研委员会简报", "Opportunity Memo"),
        ("私有投资公司", "投研工作台"),
        ("Red Team Audit", "Risk Audit"),
        ("Red Team", "Risk Auditor"),
        ("Chairman Brief", "Opportunity Memo"),
        ("Chairman CIO", "CIO Agent"),
        ("对应 Chairman brief", "对应 CIO Agent brief"),
        ("Chairman", "CIO Agent"),
        ("F / W / G partner", "Value / Momentum / Quality Partner"),
        ("F/W/G partner", "Value / Momentum / Quality Partner"),
        ("F / W / G", "Value / Momentum / Quality"),
        ("f_partner", "Value Partner"),
        ("w_partner", "Momentum Partner"),
        ("g_partner", "Quality Partner"),
        ("F partner", "Value Partner"),
        ("W partner", "Momentum Partner"),
        ("G partner", "Quality Partner"),
        ("K deep", "Anomaly Scanner"),
        ("Perplexity Deep Research", "Deep Research"),
        ("Perplexity", "Deep Research"),
        ("Nepha", "投研负责人"),
        ("✅", "[通过]"),
        ("❌", "[未通过]"),
        ("⚠️", "[注意]"),
        ("🔴", "[高]"),
        ("🟡", "[中]"),
        ("🟢", "[低]"),
        ("🧨", "[反证]"),
        ("📋", ""),
        ("📊", ""),
        ("🔍", ""),
        ("🛡️", ""),
        ("📎", ""),
        ("🧠", ""),
        ("💭", ""),
        ("🎯", ""),
    ]
    output = text
    for before, after in replacements:
        output = output.replace(before, after)
    output = re.sub(r"\bdata/[^\s`<>)，。；,]+", "报告中心", output)
    output = re.sub(r"Provider:\s*codex_cli", "模型通道：Codex", output, flags=re.IGNORECASE)
    return output


def split_title_detail(title: str) -> tuple[str, str]:
    if " — " in title:
        display_title, detail = title.split(" — ", 1)
        return display_title.strip(), detail.strip()
    if " - " in title:
        display_title, detail = title.split(" - ", 1)
        return display_title.strip(), detail.strip()
    return title, ""


def extract_h2_sections(markdown: str) -> list[MarkdownSection]:
    sections: list[MarkdownSection] = []
    current_title = ""
    current_lines: list[str] = []
    for line in markdown.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            if current_title:
                sections.append(
                    MarkdownSection(
                        title=clean_markdown_text(current_title),
                        anchor=f"section-{len(sections) + 1}",
                        lines=current_lines,
                    )
                )
            current_title = match.group(1)
            current_lines = []
        elif current_title:
            current_lines.append(line)
    if current_title:
        sections.append(
            MarkdownSection(
                title=clean_markdown_text(current_title),
                anchor=f"section-{len(sections) + 1}",
                lines=current_lines,
            )
        )
    return sections


def extract_summary_items(sections: list[MarkdownSection]) -> list[tuple[str, str]]:
    summary = next((section for section in sections if "摘要" in section.title), None)
    if not summary:
        return []
    items: list[tuple[str, str]] = []
    for line in summary.lines:
        match = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
        if not match:
            continue
        text = clean_markdown_text(match.group(1))
        if not text:
            continue
        label, value = split_summary_item(text)
        items.append((label, value))
        if len(items) >= 8:
            break
    return items


def split_summary_item(text: str) -> tuple[str, str]:
    if "：" in text:
        label, value = text.split("：", 1)
    elif ":" in text:
        label, value = text.split(":", 1)
    else:
        return compact_summary_text(text, 42), "查看正文"
    return compact_summary_text(label.strip(" -"), 42), compact_summary_text(value.strip() or "无", 72)


def compact_summary_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip(" ,，;；") + "..."


def clean_markdown_text(text: str) -> str:
    cleaned = re.sub(r"`([^`]+)`", r"\1", text)
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", cleaned)
    cleaned = re.sub(r"^[^\w\u4e00-\u9fff]+", "", cleaned).strip()
    return " ".join(cleaned.split())


def build_digest_cards(markdown: str, summary_items: list[tuple[str, str]]) -> list[ReportDigestCard]:
    cards = [digest_card_from_summary(label, value) for label, value in summary_items[:6]]
    decision = find_first_matching_line(
        markdown,
        (
            "机会状态",
            "Opportunity Score",
            "CIO 裁决",
            "建议 CIO Agent 二次裁决",
            "最强反对",
            "action_route",
            "CIO 路由",
        ),
    )
    if decision:
        cards.insert(
            0,
            ReportDigestCard(
                label="核心判断",
                value=compact_summary_text(decision, 68),
                note="先读这一条",
                tone="accent",
            ),
        )
    unique_cards: list[ReportDigestCard] = []
    seen: set[str] = set()
    for card in cards:
        key = f"{card.label}:{card.value}"
        if key in seen:
            continue
        unique_cards.append(card)
        seen.add(key)
        if len(unique_cards) >= 6:
            break
    return unique_cards


def digest_card_from_summary(label: str, value: str) -> ReportDigestCard:
    text = f"{label} {value}"
    if any(word in text for word in ("风险", "反对", "分歧", "待", "未", "回避", "补充")):
        tone = "warn"
    elif any(word in text for word in ("无", "0", "通过", "完成")):
        tone = "ok"
    else:
        tone = "neutral"
    return ReportDigestCard(label=label, value=value, note=digest_note_for_label(label), tone=tone)


def digest_note_for_label(label: str) -> str:
    if any(word in label for word in ("信号", "建议总数", "审计建议")):
        return "规模"
    if any(word in label for word in ("分歧", "反对", "风险")):
        return "优先复核"
    if any(word in label for word in ("待", "未")):
        return "后续动作"
    return "摘要"


def render_summary_grid(items: list[ReportDigestCard]) -> str:
    if not items:
        return ""
    cards = []
    for item in items:
        cards.append(
            "\n".join(
                [
                    f'<div class="summary-card {html.escape(item.tone)}">',
                    f'  <span class="summary-label">{html.escape(item.label)}</span>',
                    f'  <strong>{html.escape(item.value)}</strong>',
                    f'  <small>{html.escape(item.note)}</small>',
                    "</div>",
                ]
            )
        )
    return '<div class="summary-grid">' + "\n".join(cards) + "</div>"


def build_reading_panels(markdown: str, summary_items: list[tuple[str, str]]) -> list[ReadingPanel]:
    specs = [
        (
            "01",
            "先看结论",
            ("CIO 裁决", "建议 CIO Agent 二次裁决", "最强反对", "一致度", "执行摘要"),
        ),
        (
            "02",
            "抓住分歧",
            ("Agent 当前分布", "必须为真", "证据链风险", "方法论", "分歧"),
        ),
        (
            "03",
            "等待条件",
            ("等待条件", "风险触发器", "推翻本次裁决", "未关闭问题", "回填", "补充研究"),
        ),
    ]
    fallback = [f"{label}: {value}" for label, value in summary_items]
    panels: list[ReadingPanel] = []
    for index, (badge, title, keywords) in enumerate(specs):
        line = find_first_matching_line(markdown, keywords)
        if not line and index < len(fallback):
            line = fallback[index]
        panels.append(
            ReadingPanel(
                label=badge,
                title=title,
                body=compact_summary_text(line or "查看正文中的完整证据链。", 150),
            )
        )
    return panels


def find_first_matching_line(markdown: str, keywords: tuple[str, ...]) -> str:
    candidate_lines = []
    for raw_line in markdown.splitlines():
        stripped = raw_line.lstrip()
        if stripped.startswith(("#", "|", "---")):
            continue
        text = clean_markdown_text(raw_line)
        if is_useful_digest_line(text):
            candidate_lines.append(text)
    for keyword in keywords:
        for text in candidate_lines:
            if keyword in text:
                return normalize_digest_line(text)
    return ""


def is_useful_digest_line(text: str) -> bool:
    if len(text) < 8:
        return False
    if text.endswith(("：", ":")):
        return False
    if text in {"一致度: other", "一致度：other"}:
        return False
    return True


def normalize_digest_line(text: str) -> str:
    if "|" in text and ("：" in text or ":" in text):
        separator = "：" if "：" in text else ":"
        prefix, _ = text.split(separator, 1)
        return f"{prefix}{separator}见正文清单"
    return text


def render_editorial_digest(panels: list[ReadingPanel]) -> str:
    if not panels:
        return ""
    panel_html = []
    for panel in panels:
        panel_html.append(
            "\n".join(
                [
                    '<article class="reading-panel">',
                    f'  <span>{html.escape(panel.label)}</span>',
                    f'  <h3>{html.escape(panel.title)}</h3>',
                    f'  <p>{html.escape(panel.body)}</p>',
                    "</article>",
                ]
            )
        )
    return (
        '<section class="editorial-digest">'
        '<div class="digest-kicker">EDITORIAL BRIEF</div>'
        "<h2>三条线读完这份报告</h2>"
        '<div class="reading-grid">'
        + "\n".join(panel_html)
        + "</div></section>"
    )


def render_toc(items: list[tuple[str, str]]) -> str:
    if not items:
        return ""
    links = [
        f'<a href="#{html.escape(anchor)}"><span>{index:02d}</span>{html.escape(title)}</a>'
        for index, (anchor, title) in enumerate(items, start=1)
    ]
    return '<nav class="toc rail-toc">' + "\n".join(links) + "</nav>"


def markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    index = 0
    section_index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("```"):
            language = line.strip("`").strip()
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                code_lines.append(lines[index])
                index += 1
            index += 1
            lang_class = f' class="language-{html.escape(language)}"' if language else ""
            output.append(f"<pre><code{lang_class}>{html.escape(chr(10).join(code_lines))}</code></pre>")
            continue
        if is_table_start(lines, index):
            table_html, index = parse_table(lines, index)
            output.append(table_html)
            continue
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            text = clean_markdown_text(heading.group(2))
            if level == 2:
                section_index += 1
                output.append(f'<h2 id="section-{section_index}">{inline_markdown(text)}</h2>')
            else:
                output.append(f"<h{level}>{inline_markdown(text)}</h{level}>")
            index += 1
            continue
        if re.match(r"^\s*---+\s*$", line):
            output.append("<hr>")
            index += 1
            continue
        if line.startswith(">"):
            quote_lines: list[str] = []
            while index < len(lines) and lines[index].startswith(">"):
                quote_lines.append(lines[index].lstrip("> ").strip())
                index += 1
            output.append(f"<blockquote>{inline_markdown(' '.join(quote_lines))}</blockquote>")
            continue
        if re.match(r"^\s*[-*]\s+", line):
            html_list, index = parse_list(lines, index, ordered=False)
            output.append(html_list)
            continue
        if re.match(r"^\s*\d+\.\s+", line):
            html_list, index = parse_list(lines, index, ordered=True)
            output.append(html_list)
            continue
        paragraph_lines: list[str] = []
        while index < len(lines) and lines[index].strip() and not is_block_start(lines, index):
            paragraph_lines.append(lines[index].strip())
            index += 1
        output.append(f"<p>{inline_markdown(' '.join(paragraph_lines))}</p>")
    return "\n".join(output)


def arrange_report_sections(body_html: str) -> str:
    pattern = re.compile(r'(<h2 id="(section-\d+)">(.+?)</h2>)(.*?)(?=<h2 id="section-\d+">|$)', re.S)
    matches = list(pattern.finditer(body_html))
    if not matches:
        return body_html
    output = [body_html[: matches[0].start()]]
    for match in matches:
        heading_html, anchor, title_html, section_body = match.groups()
        title = html.unescape(re.sub(r"<.*?>", "", title_html)).strip()
        if should_collapse_section(title):
            output.append(
                "\n".join(
                    [
                        '<details class="report-section report-disclosure">',
                        f'  <summary id="{html.escape(anchor)}"><span>{title_html}</span><small>展开完整证据</small></summary>',
                        f'  <div class="disclosure-body">{section_body}</div>',
                        "</details>",
                    ]
                )
            )
        else:
            output.append(f'<section class="report-section">{heading_html}{section_body}</section>')
    return "\n".join(output)


def should_collapse_section(title: str) -> bool:
    return any(keyword in title for keyword in ("附录", "原始", "日志", "规则审计发现"))


def is_block_start(lines: list[str], index: int) -> bool:
    line = lines[index]
    return bool(
        line.startswith("```")
        or re.match(r"^#{1,6}\s+", line)
        or re.match(r"^\s*---+\s*$", line)
        or line.startswith(">")
        or re.match(r"^\s*[-*]\s+", line)
        or re.match(r"^\s*\d+\.\s+", line)
        or is_table_start(lines, index)
    )


def parse_list(lines: list[str], index: int, *, ordered: bool) -> tuple[str, int]:
    tag = "ol" if ordered else "ul"
    pattern = r"^\s*\d+\.\s+(.+)$" if ordered else r"^\s*[-*]\s+(.+)$"
    items: list[str] = []
    while index < len(lines):
        match = re.match(pattern, lines[index])
        if not match:
            break
        items.append(f"<li>{inline_markdown(match.group(1).strip())}</li>")
        index += 1
    return f"<{tag}>" + "".join(items) + f"</{tag}>", index


def is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return "|" in lines[index] and bool(re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", lines[index + 1]))


def parse_table(lines: list[str], index: int) -> tuple[str, int]:
    header = split_table_row(lines[index])
    index += 2
    body_rows: list[list[str]] = []
    while index < len(lines) and "|" in lines[index] and lines[index].strip():
        body_rows.append(split_table_row(lines[index]))
        index += 1
    head_html = "".join(f"<th>{inline_markdown(cell)}</th>" for cell in header)
    rows_html = []
    for row in body_rows:
        padded = row + [""] * max(0, len(header) - len(row))
        rows_html.append("<tr>" + "".join(f"<td>{inline_markdown(cell)}</td>" for cell in padded[: len(header)]) + "</tr>")
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + head_html
        + "</tr></thead><tbody>"
        + "".join(rows_html)
        + "</tbody></table></div>",
        index,
    )


def split_table_row(line: str) -> list[str]:
    stripped = strip_table_bounds(line)
    cells: list[str] = []
    current: list[str] = []
    for index, char in enumerate(stripped):
        if char == "|" and not is_escaped_pipe(stripped, index):
            cells.append(clean_table_cell("".join(current)))
            current = []
            continue
        current.append(char)
    cells.append(clean_table_cell("".join(current)))
    return cells


def strip_table_bounds(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not is_escaped_pipe(stripped, len(stripped) - 1):
        stripped = stripped[:-1]
    return stripped


def is_escaped_pipe(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def clean_table_cell(cell: str) -> str:
    return cell.strip().replace(r"\|", "|")


SAFE_LINK_SCHEMES = {"http", "https", "mailto"}


def render_inline_link(match: re.Match[str]) -> str:
    label = match.group(1)
    raw_url = html.unescape(match.group(2)).strip()
    if not is_safe_link_url(raw_url):
        return label
    href = html.escape(raw_url, quote=True)
    if raw_url.startswith("#"):
        return f'<a href="{href}">{label}</a>'
    return f'<a href="{href}" target="_blank" rel="noopener noreferrer">{label}</a>'


def is_safe_link_url(url: str) -> bool:
    if url.startswith("#"):
        return True
    parsed = urlsplit(url)
    return parsed.scheme.lower() in SAFE_LINK_SCHEMES


def inline_markdown(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\[(.+?)\]\((.+?)\)", render_inline_link, escaped)
    return escaped


REPORT_CSS = r"""
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500;700&family=Noto+Sans+SC:wght@400;500;700;800&family=Noto+Serif+SC:wght@600;700;900&display=swap');
:root {
  color-scheme: dark;
  --bg: #03080a;
  --panel: #071113;
  --panel-strong: #0b181b;
  --text: #f4f8f8;
  --muted: #9cacb2;
  --faint: #607176;
  --line: rgba(95, 234, 255, .18);
  --line-strong: rgba(32, 245, 208, .44);
  --accent: #20f5d0;
  --accent-2: #5feaff;
  --warn: #ffcc66;
  --danger: #ff7d7d;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  min-height: 100vh;
  background:
    radial-gradient(circle at 16% 4%, rgba(32, 245, 208, .13), transparent 26rem),
    radial-gradient(circle at 80% 10%, rgba(95, 234, 255, .08), transparent 24rem),
    linear-gradient(135deg, #020607 0%, #061112 52%, #020607 100%);
  color: var(--text);
  font-family: "Noto Sans SC", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.74;
}
body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(255,255,255,.028) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.026) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: linear-gradient(to bottom, rgba(0,0,0,.7), rgba(0,0,0,.1));
}
.report-frame {
  width: min(1680px, 100%);
  margin: 0 auto;
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 28px;
  padding: 28px;
}
.report-rail {
  position: sticky;
  top: 28px;
  height: calc(100vh - 56px);
  padding: 22px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: rgba(7, 17, 19, .76);
  backdrop-filter: blur(18px);
  overflow: auto;
}
.rail-mark {
  color: var(--accent);
  font: 700 12px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: .12em;
  text-transform: uppercase;
}
.rail-title {
  margin-top: 12px;
  font-size: 20px;
  font-weight: 800;
  line-height: 1.35;
}
.toc {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.rail-toc { margin-top: 28px; }
.page-toc {
  display: none;
  margin: 20px 0;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: rgba(7, 17, 19, .72);
}
.toc a {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
  padding: 10px 11px;
  border: 1px solid transparent;
  border-radius: 12px;
  color: var(--muted);
  text-decoration: none;
  font-size: 13px;
  line-height: 1.35;
}
.toc a:hover {
  color: var(--text);
  border-color: var(--line);
  background: rgba(32, 245, 208, .06);
}
.toc a span {
  color: var(--accent);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.report-page {
  min-width: 0;
}
.report-hero,
.editorial-digest,
.report-content {
  border: 1px solid var(--line);
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(9, 19, 22, .93), rgba(4, 10, 12, .94));
  box-shadow: 0 24px 80px rgba(0, 0, 0, .28);
}
.report-hero {
  padding: clamp(26px, 4vw, 58px);
  overflow: hidden;
  position: relative;
}
.report-hero::after {
  content: "";
  position: absolute;
  right: -140px;
  top: -160px;
  width: 420px;
  height: 420px;
  border-radius: 999px;
  border: 1px solid rgba(32, 245, 208, .2);
  background: radial-gradient(circle, rgba(32, 245, 208, .12), transparent 58%);
}
.hero-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 28px;
  align-items: end;
}
.eyebrow {
  color: var(--accent);
  font: 700 12px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: .16em;
  text-transform: uppercase;
}
h1 {
  max-width: 980px;
  margin: 18px 0 0;
  font-family: "Noto Serif SC", "Source Han Serif SC", serif;
  font-weight: 900;
  font-size: clamp(36px, 5vw, 78px);
  line-height: 1.08;
  letter-spacing: 0;
}
.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 22px;
}
.meta-chip {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  min-height: 32px;
  padding: 6px 12px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  color: #bffbf0;
  background: rgba(32, 245, 208, .06);
  font: 700 12px/1.35 ui-monospace, SFMono-Regular, Menlo, monospace;
  overflow-wrap: anywhere;
}
.meta-chip.report-id {
  color: var(--text);
  border-color: rgba(255, 255, 255, .18);
  background: rgba(255, 255, 255, .04);
}
.hero-note {
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 16px;
  background: rgba(1, 7, 8, .52);
}
.hero-note strong {
  display: block;
  margin-bottom: 6px;
  color: var(--accent-2);
}
.hero-note span {
  display: block;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.65;
}
.summary-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 32px;
}
.summary-card {
  position: relative;
  min-height: 112px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: rgba(255, 255, 255, .035);
  overflow: hidden;
}
.summary-card::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--accent);
  opacity: .8;
}
.summary-card.warn::before { background: var(--warn); }
.summary-card.ok::before { background: #67f77b; }
.summary-card.accent::before { background: var(--accent-2); }
.summary-card.warn {
  border-color: rgba(255, 204, 102, .28);
  background: rgba(255, 204, 102, .045);
}
.summary-label {
  display: block;
  margin-bottom: 10px;
  color: var(--muted);
  font-size: 12px;
}
.summary-card strong {
  display: block;
  color: var(--text);
  font-size: 21px;
  line-height: 1.2;
  overflow-wrap: anywhere;
}
.summary-card small {
  display: block;
  margin-top: 14px;
  color: var(--faint);
  font: 700 11px/1.2 "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  text-transform: uppercase;
}
.editorial-digest {
  margin-top: 22px;
  padding: clamp(22px, 3vw, 36px);
}
.digest-kicker {
  color: var(--accent);
  font: 700 12px/1.2 "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: .14em;
}
.editorial-digest h2 {
  margin: 10px 0 22px;
  font-family: "Noto Serif SC", "Source Han Serif SC", serif;
  font-size: clamp(25px, 3vw, 42px);
  line-height: 1.16;
}
.reading-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.reading-panel {
  min-height: 176px;
  padding: 18px;
  border: 1px solid rgba(95, 234, 255, .2);
  border-radius: 14px;
  background:
    linear-gradient(180deg, rgba(32, 245, 208, .055), transparent 64%),
    rgba(255, 255, 255, .028);
}
.reading-panel span {
  color: var(--accent);
  font: 700 12px/1.2 "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
.reading-panel h3 {
  margin: 22px 0 10px;
  font-size: 20px;
  line-height: 1.25;
}
.reading-panel p {
  margin: 0;
  color: var(--muted);
  font-size: 15px;
  line-height: 1.72;
}
.report-content {
  margin-top: 22px;
  padding: clamp(24px, 3.6vw, 54px);
}
.report-content h1 { display: none; }
.report-section {
  padding: 26px 0 30px;
  border-top: 1px solid rgba(95, 234, 255, .16);
}
.report-section:first-of-type {
  padding-top: 0;
  border-top: 0;
}
.report-content h2 {
  margin: 0 0 18px;
  padding-left: 18px;
  border-left: 3px solid var(--accent);
  color: var(--text);
  font-family: "Noto Serif SC", "Source Han Serif SC", serif;
  font-weight: 900;
  font-size: clamp(26px, 3vw, 44px);
  line-height: 1.2;
}
.report-content h3 {
  margin: 32px 0 14px;
  color: #d7fffa;
  font-size: clamp(20px, 2vw, 30px);
  line-height: 1.28;
}
.report-content h4 {
  margin: 22px 0 10px;
  color: var(--accent-2);
  font-size: 18px;
}
.report-content p,
.report-content li {
  color: #e8eff1;
  font-size: 17px;
}
.report-content ul,
.report-content ol {
  margin: 12px 0 24px;
  padding-left: 1.35rem;
}
.report-content li + li { margin-top: 7px; }
.report-content strong {
  color: #ffffff;
  font-weight: 800;
}
.report-content code {
  padding: 2px 6px;
  border: 1px solid rgba(95, 234, 255, .22);
  border-radius: 7px;
  color: #cffbf4;
  background: rgba(95, 234, 255, .07);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  overflow-wrap: anywhere;
}
blockquote {
  margin: 18px 0 24px;
  padding: 16px 18px;
  border-left: 3px solid var(--accent);
  border-radius: 12px;
  color: #d6e8e9;
  background: rgba(32, 245, 208, .055);
}
pre {
  margin: 18px 0 26px;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 14px;
  overflow: auto;
  background: #020608;
}
pre code {
  padding: 0;
  border: 0;
  background: transparent;
  color: #c6d5d8;
  font-size: 13px;
  line-height: 1.65;
}
hr {
  height: 1px;
  margin: 30px 0;
  border: 0;
  background: linear-gradient(90deg, transparent, var(--line-strong), transparent);
}
.table-wrap {
  width: 100%;
  margin: 18px 0 30px;
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 14px;
}
table {
  width: 100%;
  min-width: 760px;
  border-collapse: collapse;
}
th,
td {
  padding: 13px 14px;
  border-bottom: 1px solid rgba(95, 234, 255, .12);
  text-align: left;
  vertical-align: top;
}
th {
  color: var(--accent);
  background: rgba(32, 245, 208, .065);
  font-size: 13px;
  white-space: nowrap;
}
td {
  color: #dfe8ea;
  font-size: 14px;
}
tr:last-child td { border-bottom: 0; }
a { color: var(--accent-2); }
.report-disclosure {
  padding: 0;
  border-top: 1px solid rgba(95, 234, 255, .16);
}
.report-disclosure summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 22px 0;
  cursor: pointer;
  color: var(--text);
  font-family: "Noto Serif SC", "Source Han Serif SC", serif;
  font-size: clamp(24px, 2.5vw, 36px);
  font-weight: 900;
  list-style: none;
}
.report-disclosure summary::-webkit-details-marker { display: none; }
.report-disclosure summary span {
  padding-left: 18px;
  border-left: 3px solid var(--warn);
}
.report-disclosure summary small {
  flex: 0 0 auto;
  color: var(--warn);
  font: 700 12px/1.2 "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
.disclosure-body {
  padding-bottom: 28px;
}
@media (max-width: 1100px) {
  .report-frame {
    display: block;
    padding: 18px;
  }
  .report-rail { display: none; }
  .page-toc { display: flex; }
  .hero-grid { grid-template-columns: 1fr; }
  .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .reading-grid { grid-template-columns: 1fr; }
}
@media (max-width: 680px) {
  .report-frame { padding: 10px; }
  .report-hero,
  .editorial-digest,
  .report-content {
    border-radius: 12px;
  }
  .summary-grid { grid-template-columns: 1fr; }
  .meta-chip { width: 100%; }
  .report-content p,
  .report-content li { font-size: 15px; }
}
@media print {
  body { background: #fff; color: #000; }
  .report-frame { display: block; padding: 0; }
  .report-rail,
  .page-toc,
  .hero-note { display: none; }
  .report-hero,
  .report-content {
    box-shadow: none;
    border-color: #ddd;
    background: #fff;
    color: #000;
  }
  .report-content p,
  .report-content li,
  td { color: #111; }
}
"""
