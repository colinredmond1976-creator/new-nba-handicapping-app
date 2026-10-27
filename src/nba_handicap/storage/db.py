import json
import math
import sqlite3
from datetime import date, timezone
from pathlib import Path

from nba_handicap.models.schemas import (
    BetLeg,
    DashboardPayload,
    GameCard,
    LegStatus,
    PerformanceSummary,
    RunHeartbeat,
    VerificationStatus,
)


class Database:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS picks (
                leg_id TEXT PRIMARY KEY, game_id TEXT NOT NULL,
                game_date TEXT NOT NULL, away_team TEXT NOT NULL,
                home_team TEXT NOT NULL, matchup TEXT NOT NULL,
                market_type TEXT NOT NULL, player_name TEXT, stat_category TEXT,
                line REAL NOT NULL, side TEXT NOT NULL, odds_american INTEGER NOT NULL,
                implied_prob REAL NOT NULL, model_prob REAL NOT NULL, edge REAL NOT NULL,
                status TEXT NOT NULL, tank01_actual REAL, bref_actual REAL,
                verification_status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_logs (
                run_id TEXT PRIMARY KEY, timestamp_utc TEXT NOT NULL,
                status TEXT NOT NULL, games_processed INTEGER NOT NULL,
                legs_graded INTEGER NOT NULL, discrepancies_flagged INTEGER NOT NULL,
                message TEXT NOT NULL
            );
        """)

    def close(self) -> None:
        self.connection.close()

    def save_daily_cards(self, cards: list[GameCard]) -> None:
        with self.connection:
            for card in cards:
                for leg in card.legs:
                    if leg.game_id != card.game_id or leg.game_date != card.game_date:
                        raise ValueError("Leg game identity must match its card")
                    values = leg.model_dump(mode="json")
                    values.update(away_team=card.away_team, home_team=card.home_team)
                    columns = list(values)
                    self.connection.execute(
                        f"INSERT INTO picks ({', '.join(columns)}) VALUES "
                        f"({', '.join('?' for _ in columns)})",
                        [values[column] for column in columns],
                    )

    def get_pending_legs(self, game_date: date | str) -> list[BetLeg]:
        rows = self.connection.execute(
            "SELECT * FROM picks WHERE game_date = ? AND status = ? ORDER BY rowid",
            (str(game_date), LegStatus.PENDING.value),
        )
        return [BetLeg.model_validate(dict(row)) for row in rows]

    def update_graded_leg(self, leg: BetLeg) -> None:
        if leg.tank01_actual is None or leg.bref_actual is None:
            verification = VerificationStatus.DISCREPANCY
        elif math.isclose(leg.tank01_actual, leg.bref_actual, rel_tol=0, abs_tol=1e-5):
            verification = VerificationStatus.CONFIRMED
        else:
            verification = VerificationStatus.DISCREPANCY
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE picks SET status = ?, tank01_actual = ?, bref_actual = ?, "
                "verification_status = ? WHERE leg_id = ?",
                (leg.status.value, leg.tank01_actual, leg.bref_actual,
                 verification.value, leg.leg_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Unknown leg: {leg.leg_id}")

    def record_heartbeat(self, heartbeat: RunHeartbeat) -> None:
        values = heartbeat.model_dump(mode="json")
        with self.connection:
            self.connection.execute(
                "INSERT INTO run_logs VALUES (?, ?, ?, ?, ?, ?, ?)", tuple(values.values())
            )

    def compute_performance_summary(self) -> PerformanceSummary:
        rows = self.connection.execute("SELECT status, odds_american FROM picks").fetchall()
        wins = sum(row["status"] == LegStatus.WON.value for row in rows)
        losses = sum(row["status"] == LegStatus.LOST.value for row in rows)
        pushes = sum(row["status"] == LegStatus.PUSH.value for row in rows)
        net_units = -float(losses)
        for row in rows:
            if row["status"] == LegStatus.WON.value:
                odds = row["odds_american"]
                if odds == 0:
                    raise ValueError("American odds cannot be zero for a winning leg")
                net_units += odds / 100 if odds > 0 else 100 / abs(odds)
        settled = wins + losses + pushes
        return PerformanceSummary(
            total_picks=len(rows), wins=wins, losses=losses, pushes=pushes,
            win_rate=wins / (wins + losses) if wins + losses else 0.0,
            net_units=net_units, roi_pct=net_units / settled * 100 if settled else 0.0,
        )

    def export_dashboard_json(self, filepath: str | Path, game_date: date | str | None = None) -> None:
        row = self.connection.execute(
            "SELECT * FROM run_logs ORDER BY timestamp_utc DESC, rowid DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise ValueError("A heartbeat is required to export the dashboard")
        heartbeat = RunHeartbeat.model_validate(dict(row))
        if heartbeat.timestamp_utc.utcoffset() is None:
            raise ValueError("Heartbeat timestamp must include a timezone")
        today = str(game_date) if game_date is not None else heartbeat.timestamp_utc.astimezone(timezone.utc).date().isoformat()
        rows = self.connection.execute("SELECT * FROM picks ORDER BY rowid").fetchall()
        cards: dict[tuple[str, str], dict] = {}
        for pick in rows:
            if pick["game_date"] == today:
                key = (pick["game_id"], pick["game_date"])
                card = cards.setdefault(key, {
                    "game_id": pick["game_id"], "game_date": pick["game_date"],
                    "away_team": pick["away_team"], "home_team": pick["home_team"],
                    "legs": [],
                })
                card["legs"].append(BetLeg.model_validate(dict(pick)))
        payload = DashboardPayload(
            heartbeat=heartbeat, summary=self.compute_performance_summary(),
            todays_cards=[GameCard.model_validate(card) for card in cards.values()],
            history=[BetLeg.model_validate(dict(pick)) for pick in rows],
        )
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
