from __future__ import annotations

from chairman.fallback.raw_passthrough import fallback_passthrough


def test_fallback_when_schema_invalid(tmp_path):
    data_dir = tmp_path / "data"
    signal_dir = data_dir / "research_signals"
    rec_dir = data_dir / "recommendations" / "20260513" / "f_partner"
    signal_dir.mkdir(parents=True)
    rec_dir.mkdir(parents=True)
    (signal_dir / "RS-20260513-001.yaml").write_text(
        """
research_signal:
  research_signal_id: RS-20260513-001
  signal_summary: mock
""",
        encoding="utf-8",
    )
    (rec_dir / "R-FP-20260513-001.yaml").write_text(
        """
recommendation:
  recommendation_id: R-FP-20260513-001
  agent_id: f_partner
  direction: invalid_direction
""",
        encoding="utf-8",
    )

    output_path = fallback_passthrough(
        data_dir=data_dir,
        date="2026-05-13",
        brief_type="morning",
        failure_reason="schema invalid",
    )

    content = output_path.read_text(encoding="utf-8")
    assert "Chairman 失败" in content
    assert "原始建议转发" in content
    assert "R-FP-20260513-001" in content
    assert (data_dir / "errors" / "CHAIRMAN-FAIL-20260513-01.log").exists()
