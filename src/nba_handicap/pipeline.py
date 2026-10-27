from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from nba_handicap.analysis.grader import grade_leg
from nba_handicap.analysis.selector import select_four_legs_for_game
from nba_handicap.api.bref import BRefBoxScoreClient, resolve_bref_boxscore_url
from nba_handicap.api.live_provider import Tank01CandidateProvider
from nba_handicap.api.odds import Tank01OddsClient, extract_tank01_stats
from nba_handicap.models.schemas import LegStatus, RunHeartbeat, RunStatus, VerificationStatus
from nba_handicap.storage.db import Database


def run_daily_pipeline(db_path: str, output_json_path: str, run_date: str, *,
                       tank01_client=None, bref_client=None, candidate_provider=None,
                       bref_url_resolver=None) -> RunHeartbeat:
    day = date.fromisoformat(run_date)
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)
    errors = []
    graded_count = 0
    discrepancy_count = 0
    games_processed = 0
    completed = 0
    reused_cards = 0
    owned_clients = []
    try:
        if candidate_provider is None:
            if tank01_client is None:
                tank01_client = Tank01OddsClient()
                owned_clients.append(tank01_client)
            candidate_provider = Tank01CandidateProvider(tank01_client)
            if bref_client is None:
                bref_client = BRefBoxScoreClient()
                owned_clients.append(bref_client)
            if bref_url_resolver is None:
                bref_url_resolver = resolve_bref_boxscore_url
        pending = db.get_pending_legs(day - timedelta(days=1))
        sources = {}
        for leg in pending:
            if leg.game_id not in sources:
                tank, bref = {}, {}
                try:
                    if tank01_client is None:
                        raise ValueError("Tank01 client is required to grade pending legs")
                    tank = extract_tank01_stats(tank01_client.get_box_score(leg.game_id))
                except Exception as exc:
                    errors.append(f"Tank01 {leg.game_id}: {exc}")
                try:
                    if bref_client is None or bref_url_resolver is None:
                        raise ValueError("Basketball-Reference client and URL resolver are required")
                    bref = bref_client.get_box_score(bref_url_resolver(leg.game_id))
                except Exception as exc:
                    errors.append(f"Basketball-Reference {leg.game_id}: {exc}")
                sources[leg.game_id] = (tank, bref)
            try:
                graded = grade_leg(leg, *sources[leg.game_id])
                db.update_graded_leg(graded)
                if graded.status != LegStatus.PENDING:
                    graded_count += 1
                    completed += 1
                if graded.verification_status == VerificationStatus.DISCREPANCY:
                    discrepancy_count += 1
            except Exception as exc:
                errors.append(f"Leg {leg.leg_id}: {exc}")
        try:
            if candidate_provider is None:
                raise ValueError("A candidate provider is required")
            games = candidate_provider(day.isoformat())
            for game in games:
                try:
                    if db.has_daily_card(game["game_id"], day):
                        games_processed += 1
                        completed += 1
                        reused_cards += 1
                        continue
                    card = select_four_legs_for_game(
                        game["game_id"], day.isoformat(), game["away_team"],
                        game["home_team"], game["candidates"],
                    )
                    db.save_daily_cards([card])
                    games_processed += 1
                    completed += 1
                except Exception as exc:
                    errors.append(f"Game {game.get('game_id', '?')}: {exc}")
        except Exception as exc:
            errors.append(f"Candidate provider: {exc}")
        if errors or discrepancy_count:
            status = RunStatus.PARTIAL if completed else RunStatus.FAILED
        else:
            status = RunStatus.SUCCESS
        heartbeat = RunHeartbeat(
            run_id=str(uuid4()), timestamp_utc=datetime.now(timezone.utc), status=status,
            games_processed=games_processed, legs_graded=graded_count,
            discrepancies_flagged=discrepancy_count,
            message="; ".join(errors) if errors else ("Discrepancies flagged" if discrepancy_count else (f"Completed; reused {reused_cards} existing cards" if reused_cards else "Completed")),
        )
        db.record_heartbeat(heartbeat)
        db.export_dashboard_json(output_json_path, game_date=day)
        return heartbeat
    finally:
        for client in owned_clients:
            client.close()
        db.close()
