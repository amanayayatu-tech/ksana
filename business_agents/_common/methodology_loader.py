"""Load frozen methodology markdown into system prompts."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

METHODOLOGY_FILES = {
    "fengliu_reverse_odds": "fengliu_v0.5.1.md",
    "wanmu_single_sided": "wanmu_v0.3.1.md",
    "liguofei_zen_value": "liguofei_v0.5.1.md",
    "research_system_event_bayesian": "research_system_v0.3.md",
}

DISPLAY_NAMES = {
    "fengliu_reverse_odds": ("冯柳：逆向赔率选择法", "trading_agent"),
    "wanmu_single_sided": ("万木：单边翻倍协同投研法", "trading_agent"),
    "liguofei_zen_value": ("李国飞：禅式高确定性价值投资", "trading_agent"),
    "research_system_event_bayesian": ("4.1 研究体系：事件贝叶斯研究上游", "research_upstream"),
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
        path = self.project_root / "methodologies" / METHODOLOGY_FILES[methodology_id]
        content = _trim_methodology(path.read_text(encoding="utf-8"))
        display_name, role = DISPLAY_NAMES[methodology_id]
        return self.template_env.get_template("base_system_prompt.j2").render(
            agent_display_name=display_name,
            agent_role=role,
            methodology_content=content,
        )


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
