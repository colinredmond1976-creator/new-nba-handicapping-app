import json
from pathlib import Path

from nba_handicap.cli import _demo_candidates
from nba_handicap.models.schemas import DashboardPayload
from nba_handicap.pipeline import run_daily_pipeline


def test_dashboard_fixture_matches_schema():
    fixture = Path(__file__).with_name("test_dashboard_payload.json")
    payload = DashboardPayload.model_validate_json(fixture.read_text())
    assert len(payload.todays_cards[0].legs) == 4
    assert len(payload.history) == 4


def test_exported_dashboard_payload_matches_schema(tmp_path):
    output = tmp_path / "dashboard_payload.json"
    heartbeat = run_daily_pipeline(":memory:", str(output), "2026-10-27",
                                   candidate_provider=_demo_candidates)
    payload = DashboardPayload.model_validate(json.loads(output.read_text()))
    assert payload.heartbeat.run_id == heartbeat.run_id
    assert len(payload.todays_cards) == 1
    assert len(payload.todays_cards[0].legs) == 4
    assert len(payload.history) == 4
