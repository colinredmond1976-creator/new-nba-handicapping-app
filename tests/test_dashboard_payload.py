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


def test_export_preserves_nba_review_and_provider_values(tmp_path):
    from nba_handicap.storage.db import Database

    db_path = tmp_path / 'picks.sqlite'
    output = tmp_path / 'payload.json'
    run_daily_pipeline(str(db_path), str(output), '2026-10-27', candidate_provider=_demo_candidates)
    db = Database(db_path)
    leg_id = db.connection.execute('SELECT leg_id FROM picks LIMIT 1').fetchone()[0]
    db.connection.execute('CREATE TABLE nba_reconciliations (leg_id TEXT PRIMARY KEY, nba_actual REAL, nba_outcome TEXT, source_url TEXT, reviewed_at TEXT)')
    db.connection.execute('INSERT INTO nba_reconciliations VALUES (?, ?, ?, ?, ?)', (leg_id, 3, 'WON', 'https://www.nba.com/game/example', '2026-10-28T00:00:00Z'))
    db.connection.commit()
    db.export_dashboard_json(output, game_date='2026-10-27')
    result = json.loads(output.read_text())
    leg = next(item for item in result['history'] if item['leg_id'] == leg_id)
    assert leg['nba_actual'] == 3
    assert leg['nba_outcome'] == 'WON'
    assert leg['nba_source_url'] == 'https://www.nba.com/game/example'
    assert leg['tank01_actual'] is None and leg['bref_actual'] is None
    db.close()
