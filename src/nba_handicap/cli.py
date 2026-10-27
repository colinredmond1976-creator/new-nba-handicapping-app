import argparse
from datetime import datetime, timezone

from nba_handicap.models.schemas import BetLeg
from nba_handicap.pipeline import run_daily_pipeline


def _demo_candidates(run_date: str) -> list[dict]:
    candidates = [BetLeg(
        leg_id=f"demo-{run_date}-{index}", game_id=f"demo-{run_date}", game_date=run_date,
        matchup="Demo Away at Demo Home", market_type="PLAYER_PROP",
        player_name=f"Demo Player {index}", stat_category="PTS", line=20.5,
        side="OVER", odds_american=-110, implied_prob=0.0, model_prob=0.60, edge=0.0,
    ) for index in range(4)]
    return [{"game_id": f"demo-{run_date}", "away_team": "Demo Away",
             "home_team": "Demo Home", "candidates": candidates}]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the daily NBA handicapping pipeline")
    parser.add_argument("--date", help="Run date in YYYYMMDD format")
    parser.add_argument("--demo", action="store_true", help="Use synthetic offline data")
    args = parser.parse_args()
    try:
        day = datetime.strptime(args.date, "%Y%m%d").date() if args.date else datetime.now(timezone.utc).date()
    except ValueError:
        parser.error("--date must be a valid YYYYMMDD date")
    if args.demo:
        heartbeat = run_daily_pipeline(":memory:", "data/dashboard_payload.json", day.isoformat(),
                                       candidate_provider=_demo_candidates)
    else:
        heartbeat = run_daily_pipeline("data/nba_handicap.sqlite", "data/dashboard_payload.json",
                                       day.isoformat())
    print(f"{heartbeat.status.value}: data/dashboard_payload.json")
    if heartbeat.status != "SUCCESS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
