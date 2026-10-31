import math
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from uuid import NAMESPACE_URL, uuid5

from nba_handicap.analysis.selector import american_to_implied_prob
from nba_handicap.models.schemas import BetLeg


class Tank01CandidateProvider:
    def __init__(self, client, projection_adjustments: dict[str, float] | None = None):
        self.client = client
        self.projection_adjustments = projection_adjustments or {}

    def __call__(self, run_date: str) -> list[dict]:
        day = date.fromisoformat(run_date)
        payload = self.client.get_betting_odds(day.strftime("%Y%m%d"))
        if payload.get("error") or payload.get("statusCode", 200) != 200:
            raise ValueError(f"Tank01 odds error: {payload.get('error', payload.get('statusCode'))}")
        body = payload.get("body")
        if isinstance(body, dict):
            games = [{**game, "gameID": game.get("gameID", key)} for key, game in body.items()]
        elif isinstance(body, list):
            games = body
        else:
            raise ValueError("Tank01 odds response has no valid body")
        names = {}
        if any(game.get("playerProps") for game in games):
            players = self.client.get_player_list()
            if players.get("error") or players.get("statusCode", 200) != 200 or not isinstance(players.get("body"), list):
                raise ValueError("Tank01 player list is unavailable")
            names = {str(player["playerID"]): player["longName"] for player in players["body"]
                     if player.get("playerID") and player.get("longName")}
        return [self._game(game, day, names) for game in games]

    def get_start_times(self, run_date: str) -> dict[str, str]:
        day = date.fromisoformat(run_date)
        payload = self.client.get_team_schedules()
        if payload.get("error") or payload.get("statusCode", 200) != 200 or not isinstance(payload.get("body"), list):
            raise ValueError("Tank01 team schedules are unavailable")
        result = {}
        for team in payload["body"]:
            schedule = team.get("teamSchedule", {})
            if not isinstance(schedule, dict):
                continue
            for game in schedule.values():
                if not isinstance(game, dict) or game.get("gameDate") != day.strftime("%Y%m%d"):
                    continue
                try:
                    game_id = game["gameID"]
                    stamp = float(game["gameTime_epoch"])
                    if not math.isfinite(stamp):
                        continue
                    start = datetime.fromtimestamp(stamp, tz=timezone.utc)
                    if start.astimezone(ZoneInfo("America/Toronto")).date() != day:
                        continue
                except (KeyError, TypeError, ValueError, OverflowError, OSError):
                    continue
                value = start.isoformat()
                if game_id in result and result[game_id] != value:
                    raise ValueError(f"Conflicting start times for {game_id}")
                result[game_id] = value
        return result

    def _game(self, game: dict, day: date, names: dict) -> dict:
        game_id, away, home = game["gameID"], game["awayTeam"], game["homeTeam"]
        if game.get("gameDate") and game["gameDate"] != day.strftime("%Y%m%d"):
            raise ValueError(f"Unexpected game date for {game_id}")
        candidates = []

        def add(market, side, line, odds, probability, player=None, stat=None):
            adjustment = self.projection_adjustments.get(stat or market, 0.0)
            model = probability + adjustment
            if not math.isfinite(model) or not 0 <= model <= 1:
                raise ValueError("Adjusted probability must be between 0 and 1")
            implied = american_to_implied_prob(odds)
            key = f"{game_id}|{market}|{player}|{stat}|{side}|{line}"
            candidates.append(BetLeg(
                leg_id=str(uuid5(NAMESPACE_URL, key)), game_id=game_id, game_date=day,
                matchup=f"{away} @ {home}", market_type=market, player_name=player,
                stat_category=stat, line=line, side=side, odds_american=odds,
                implied_prob=implied, model_prob=model, edge=model - implied,
            ))

        for prop in game.get("playerProps", []):
            player_id = str(prop["playerID"])
            if player_id not in names:
                raise ValueError(f"No Tank01 player name for {player_id}")
            markets = prop.get("propBets", {})
            for field, stat in (("pts", "PTS"), ("reb", "REB"), ("ast", "AST"),
                                ("ptsrebast", "PRA"), ("threes", "3PM"),
                                ("ptsast", "PTS_AST"), ("ptsreb", "PTS_REB"),
                                ("rebast", "REB_AST"), ("stl", "STL"),
                                ("blk", "BLK"), ("stlblk", "STL_BLK")):
                if not all(key in markets for key in (field, field + "Over", field + "Under")):
                    continue
                try:
                    line = float(markets[field])
                    over, under = int(markets[field + "Over"]), int(markets[field + "Under"])
                    op, up = american_to_implied_prob(over), american_to_implied_prob(under)
                except (TypeError, ValueError):
                    continue
                add("PLAYER_PROP", "OVER", line, over, op / (op + up), names[player_id], stat)
                add("PLAYER_PROP", "UNDER", line, under, up / (op + up), names[player_id], stat)

        books = game.get("sportsBooks", [])
        if not books:
            books = [{"sportsBook": name, "odds": value} for name, value in game.items()
                     if isinstance(value, dict) and any(key in value for key in
                        ("homeTeamML", "homeTeamSpread", "totalOver"))]
        for market, first, second, line_a, line_b, odds_a, odds_b in (
            ("SPREAD", "HOME", "AWAY", "homeTeamSpread", "awayTeamSpread", "homeTeamSpreadOdds", "awayTeamSpreadOdds"),
            ("TOTAL", "OVER", "UNDER", "totalOver", "totalUnder", "totalOverOdds", "totalUnderOdds"),
            ("MONEYLINE", "HOME", "AWAY", None, None, "homeTeamML", "awayTeamML"),
        ):
            quotes = []
            for book in books:
                odds = book.get("odds", {})
                try:
                    a, b = int(odds[odds_a]), int(odds[odds_b])
                    la = float(odds[line_a]) if line_a else 0.0
                    lb = float(odds[line_b]) if line_b else 0.0
                    if (market == "TOTAL" and la != lb) or (market == "SPREAD" and la != -lb):
                        continue
                    pa, pb = american_to_implied_prob(a), american_to_implied_prob(b)
                    quotes.append((book.get("sportsBook", "").lower(), la, lb, a, b, pa / (pa + pb)))
                except (KeyError, TypeError, ValueError):
                    continue
            for book_name in ("fanduel", "bet365", "draftkings", "betmgm"):
                chosen = next((quote for quote in quotes if quote[0] == book_name), None)
                if chosen:
                    break
            else:
                continue
            compatible = [quote[5] for quote in quotes if quote[1:3] == chosen[1:3]]
            consensus = sum(compatible) / len(compatible)
            add(market, first, chosen[1], chosen[3], consensus)
            add(market, second, chosen[2], chosen[4], 1 - consensus)
        return {"game_id": game_id, "away_team": away, "home_team": home, "candidates": candidates}
