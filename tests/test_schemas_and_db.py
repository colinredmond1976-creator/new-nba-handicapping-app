import json
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from nba_handicap.models.schemas import BetLeg, GameCard, RunHeartbeat
from nba_handicap.storage.db import Database


def test_daily_cards_grading_and_export(tmp_path):
    game_date = date(2026, 10, 27)
    legs = [BetLeg(
        leg_id=str(i), game_id="game-1", game_date=game_date,
        matchup="Away at Home", market_type="PLAYER_PROP", player_name="Player",
        stat_category="PTS", line=20.5, side="OVER", odds_american=100,
        implied_prob=0.5, model_prob=0.6, edge=0.1,
    ) for i in range(4)]
    card = GameCard(game_id="game-1", game_date=game_date,
                    away_team="Away", home_team="Home", legs=legs)
    with pytest.raises(ValidationError):
        GameCard(game_id="game-1", game_date=game_date,
                 away_team="Away", home_team="Home", legs=legs[:3])
    db = Database(":memory:")
    try:
        db.save_daily_cards([card])
        pending = db.get_pending_legs(game_date)
        assert len(pending) == 4
        for leg, status in zip(pending, ("WON", "WON", "LOST", "PUSH")):
            db.update_graded_leg(leg.model_copy(update={
                "status": type(leg.status)(status), "tank01_actual": 21.0,
                "bref_actual": 21.0,
            }))
        assert db.get_pending_legs(game_date) == []
        summary = db.compute_performance_summary()
        assert (summary.total_picks, summary.wins, summary.losses, summary.pushes) == (4, 2, 1, 1)
        assert summary.win_rate == pytest.approx(2 / 3)
        assert summary.net_units == pytest.approx(1.0)
        assert summary.roi_pct == pytest.approx(25.0)
        db.record_heartbeat(RunHeartbeat(
            run_id="run-1", timestamp_utc=datetime(2026, 10, 27, 12, tzinfo=timezone.utc),
            status="SUCCESS", games_processed=1, legs_graded=4,
            discrepancies_flagged=0, message="Completed",
        ))
        output = tmp_path / "data" / "dashboard_payload.json"
        db.export_dashboard_json(output)
        payload = json.loads(output.read_text())
        assert payload["heartbeat"]["run_id"] == "run-1"
        assert payload["summary"]["roi_pct"] == pytest.approx(25.0)
        assert len(payload["todays_cards"]) == 1
        assert len(payload["todays_cards"][0]["legs"]) == 4
        assert len(payload["history"]) == 4
        assert all(leg["verification_status"] == "CONFIRMED" for leg in payload["history"])
    finally:
        db.close()
