import json
from datetime import date, timedelta

import pytest

from nba_handicap.analysis.selector import (american_to_decimal, american_to_implied_prob,
                                              calculate_ev, select_four_legs_for_game)
from nba_handicap.models.schemas import BetLeg, GameCard
from nba_handicap.pipeline import run_daily_pipeline
from nba_handicap.storage.db import Database


def make_leg(day, game, number, **overrides):
    fields = dict(leg_id=f"{game}-{number}", game_id=game, game_date=day,
                  matchup="Away at Home", market_type="PLAYER_PROP",
                  player_name=f"Player {number}", stat_category="PTS", line=24.5,
                  side="OVER", odds_american=-110, implied_prob=0.0,
                  model_prob=0.60, edge=0.0)
    fields.update(overrides)
    return BetLeg(**fields)


def test_odds_math():
    assert american_to_implied_prob(-110) == pytest.approx(0.5238, abs=0.0001)
    assert american_to_implied_prob(120) == pytest.approx(0.4545, abs=0.0001)
    assert american_to_decimal(120) == pytest.approx(2.2)
    assert calculate_ev(0.5, 120) == pytest.approx(0.1)
    with pytest.raises(ValueError):
        american_to_implied_prob(0)


def test_selection_priority_threshold_and_duplicates():
    day = date(2026, 10, 27)
    props = [make_leg(day, "g", n) for n in range(4)]
    spread = make_leg(day, "g", 5, market_type="SPREAD", player_name=None,
                      stat_category=None, side="HOME", model_prob=0.60)
    duplicate = make_leg(day, "g", 6, player_name="Player 0", model_prob=0.61)
    card = select_four_legs_for_game("g", day.isoformat(), "Away", "Home", props + [spread, duplicate])
    assert all(item.market_type == "PLAYER_PROP" for item in card.legs)
    assert len({(item.player_name, item.stat_category) for item in card.legs}) == 4
    props[3] = make_leg(day, "g", 3, model_prob=0.53)
    card = select_four_legs_for_game("g", day.isoformat(), "Away", "Home", props + [spread])
    assert any(item.market_type == "SPREAD" for item in card.legs)
    with pytest.raises(ValueError):
        select_four_legs_for_game("g", day.isoformat(), "Away", "Home", props)


def test_pipeline_end_to_end(tmp_path):
    day = date(2026, 10, 27)
    previous = day - timedelta(days=1)
    db_path = str(tmp_path / "picks.sqlite")
    output = tmp_path / "data" / "dashboard_payload.json"
    db = Database(db_path)
    old_legs = [make_leg(previous, "old", n) for n in range(4)]
    db.save_daily_cards([GameCard(game_id="old", game_date=previous, away_team="Away",
                                  home_team="Home", legs=old_legs)])
    db.close()

    class Tank:
        def get_box_score(self, game_id):
            assert game_id == "old"
            return {"body": {"playerStats": {str(n): {
                "longName": f"Player {n}", "pts": "28", "reb": "5", "ast": "4", "tptfgm": "2"
            } for n in range(4)}}}

    class BRef:
        def get_box_score(self, url):
            assert url == "fixture-url"
            return {"players": {f"player {n}": {"PTS": 28} for n in range(4)}}

    def provider(run_date):
        assert run_date == day.isoformat()
        return [{"game_id": "new", "away_team": "Away", "home_team": "Home",
                 "candidates": [make_leg(day, "new", n) for n in range(4)]}]

    heartbeat = run_daily_pipeline(db_path, str(output), day.isoformat(), tank01_client=Tank(),
                                   bref_client=BRef(), candidate_provider=provider,
                                   bref_url_resolver=lambda game_id: "fixture-url")
    payload = json.loads(output.read_text())
    assert heartbeat.status == "SUCCESS"
    assert (heartbeat.games_processed, heartbeat.legs_graded, heartbeat.discrepancies_flagged) == (1, 4, 0)
    assert payload["heartbeat"]["run_id"] == heartbeat.run_id
    assert payload["summary"]["wins"] == 4
    assert len(payload["todays_cards"]) == 1
    assert len(payload["todays_cards"][0]["legs"]) == 4
    assert len(payload["history"]) == 8


def test_same_day_rerun_reuses_existing_card(tmp_path):
    day = date(2026, 10, 27)
    db_path = str(tmp_path / 'picks.sqlite')
    output = tmp_path / 'dashboard_payload.json'
    candidates = [make_leg(day, 'game', n) for n in range(4)]

    def provider(_):
        return [{'game_id': 'game', 'away_team': 'Away', 'home_team': 'Home',
                 'candidates': candidates}]

    first = run_daily_pipeline(db_path, str(output), day.isoformat(), candidate_provider=provider)
    initial = json.loads(output.read_text())
    candidates.clear()
    second = run_daily_pipeline(db_path, str(output), day.isoformat(), candidate_provider=provider)
    rerun = json.loads(output.read_text())
    assert first.status == second.status == 'SUCCESS'
    assert second.games_processed == 1
    assert second.message == 'Completed; reused 1 existing cards'
    assert rerun['todays_cards'] == initial['todays_cards']
    assert rerun['history'] == initial['history']


def test_cli_partial_and_failed_exit_codes(monkeypatch, capsys):
    import sys
    from types import SimpleNamespace
    import pytest
    from nba_handicap import cli
    from nba_handicap.models.schemas import RunStatus

    monkeypatch.setattr(sys, "argv", ["nba_handicap", "--date", "20261029"])
    for status in (RunStatus.SUCCESS, RunStatus.PARTIAL, RunStatus.FAILED):
        monkeypatch.setattr(cli, "run_daily_pipeline", lambda *args, status=status: SimpleNamespace(status=status))
        if status == RunStatus.FAILED:
            with pytest.raises(SystemExit) as exc:
                cli.main()
            assert exc.value.code == 1
        else:
            cli.main()
        assert status.value in capsys.readouterr().out


def test_pipeline_exports_start_time_for_reused_cards_and_warns_on_schedule_failure(tmp_path):
    day = date(2026, 10, 31)
    db_path = str(tmp_path / "picks.sqlite")
    output = tmp_path / "dashboard_payload.json"

    class Provider:
        fail = False
        def __call__(self, run_date):
            return [{"game_id": "game", "away_team": "Away", "home_team": "Home",
                     "candidates": [make_leg(day, "game", n) for n in range(4)]}]
        def get_start_times(self, run_date):
            if self.fail:
                raise ValueError("schedule unavailable")
            return {"game": "2026-10-31T23:00:00+00:00"}

    provider = Provider()
    first = run_daily_pipeline(db_path, str(output), day.isoformat(), candidate_provider=provider)
    assert first.status == "SUCCESS"
    card = json.loads(output.read_text())["todays_cards"][0]
    assert card["game_start_time"] in ("2026-10-31T23:00:00Z", "2026-10-31T23:00:00+00:00")
    second = run_daily_pipeline(db_path, str(output), day.isoformat(), candidate_provider=provider)
    assert second.status == "SUCCESS"
    assert json.loads(output.read_text())["todays_cards"][0]["game_start_time"] == card["game_start_time"]
    provider.fail = True
    failed_schedule = run_daily_pipeline(db_path, str(output), day.isoformat(), candidate_provider=provider)
    assert failed_schedule.status == "PARTIAL"
    assert "schedule unavailable" in failed_schedule.message
    assert json.loads(output.read_text())["todays_cards"][0]["game_start_time"] is None
