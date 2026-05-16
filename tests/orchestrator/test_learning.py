from __future__ import annotations

import json

from chairman.core.brief_assembler import assemble_brief
from chairman.persistence.archive import archive_brief
from orchestrator.core.learning import (
    load_chairman_learning_context,
    rebuild_learning_from_archived_briefs,
    refresh_outcome_snapshots,
    write_json_list,
)
from tests.conftest import make_f_partner, make_g_partner, make_signal, make_w_partner


class OutcomeMarketClient:
    def get_history(self, ticker: str, period: str = "1y"):
        del ticker, period
        return [
            {"date": "2026-05-13", "close": 100, "source_url": "https://example.com/start"},
            {"date": "2026-05-14", "close": 106, "source_url": "https://example.com/one-day"},
            {"date": "2026-05-20", "close": 140, "source_url": "https://example.com/future"},
        ]


def test_archive_writes_learning_case_and_stock_timeline(tmp_path):
    data_dir = tmp_path / "data"
    brief = assemble_brief(
        research_signals=[make_signal()],
        recommendations=[make_f_partner("long"), make_w_partner("watch"), make_g_partner("watch")],
        brief_type="morning",
        date="2026-05-13",
        use_llm=False,
    )

    archive_brief(brief, data_dir)

    case_path = data_dir / "learning" / "decision_cases.json"
    cases = json.loads(case_path.read_text(encoding="utf-8"))
    assert cases[0]["case_id"] == "DC-BRIEF-20260513-AM-MOCK"
    assert cases[0]["future_data_allowed"] is False
    assert cases[0]["available_context_cutoff"] == "2026-05-13"
    assert (data_dir / "learning" / "stock_timelines" / "MOCK.json").exists()
    assert (data_dir / "learning" / "monthly_reviews" / "LEARNING-REVIEW-202605.json").exists()


def test_rebuild_learning_from_archived_briefs_backfills_old_briefs(tmp_path):
    data_dir = tmp_path / "data"
    brief = assemble_brief(
        research_signals=[make_signal()],
        recommendations=[make_f_partner("long"), make_w_partner("watch"), make_g_partner("watch")],
        brief_type="morning",
        date="2026-05-13",
        use_llm=False,
    )
    archive_dir = data_dir / "briefs" / "20260513"
    archive_dir.mkdir(parents=True)
    (archive_dir / "BRIEF-20260513-AM.json").write_text(brief.model_dump_json(), encoding="utf-8")

    path = rebuild_learning_from_archived_briefs(data_dir)

    cases = json.loads(path.read_text(encoding="utf-8"))
    assert cases[0]["source_brief_id"] == "BRIEF-20260513-AM"


def test_outcome_snapshots_do_not_read_future_rows(tmp_path):
    data_dir = tmp_path / "data"
    write_json_list(
        data_dir / "learning" / "decision_cases.json",
        [
            {
                "case_id": "DC-BRIEF-20260513-AM-MOCK",
                "ticker": "MOCK",
                "as_of_date": "2026-05-13",
                "decision_direction": "long",
                "verification_windows_days": [1, 7],
            }
        ],
    )

    refresh_outcome_snapshots(data_dir, market_client=OutcomeMarketClient(), as_of_date="2026-05-14")

    snapshots = json.loads((data_dir / "learning" / "outcome_snapshots.json").read_text(encoding="utf-8"))
    by_window = {item["window_days"]: item for item in snapshots}
    assert by_window[1]["status"] == "price_supports"
    assert by_window[1]["price_change_pct"] == 6.0
    assert by_window[7]["status"] == "pending"
    assert "price_change_pct" not in by_window[7]


def test_chairman_learning_context_is_time_safe(tmp_path):
    data_dir = tmp_path / "data"
    write_json_list(
        data_dir / "learning" / "decision_cases.json",
        [
            {
                "case_id": "DC-BRIEF-20260513-AM-MOCK",
                "source_brief_id": "BRIEF-20260513-AM",
                "ticker": "MOCK",
                "as_of_date": "2026-05-13",
                "decision_direction": "watch",
                "chairman_final_verdict": "wait",
            },
            {
                "case_id": "DC-BRIEF-20260515-AM-MOCK",
                "source_brief_id": "BRIEF-20260515-AM",
                "ticker": "MOCK",
                "as_of_date": "2026-05-15",
                "decision_direction": "avoid",
                "chairman_final_verdict": "reject",
            },
        ],
    )

    context = load_chairman_learning_context(data_dir, "MOCK", as_of_date="2026-05-14")

    assert context["prior_cases_count"] == 1
    assert context["latest_case_id"] == "DC-BRIEF-20260513-AM-MOCK"
