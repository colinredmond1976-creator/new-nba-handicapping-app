import os

import httpx
from dotenv import load_dotenv

from nba_handicap.api.bref import normalize_name


class Tank01OddsClient:
    def __init__(self) -> None:
        load_dotenv()
        host = os.environ["RAPIDAPI_HOST"]
        self.client = httpx.Client(
            base_url=f"https://{host}",
            headers={"X-RapidAPI-Key": os.environ["NBA_TANK01_RAPIDAPI_KEY"],
                     "X-RapidAPI-Host": host},
            timeout=30.0,
        )

    def get_box_score(self, game_id: str) -> dict:
        response = self.client.get("/getNBABoxScore", params={"gameID": game_id})
        response.raise_for_status()
        return response.json()

    def get_betting_odds(self, game_date: str) -> dict:
        response = self.client.get("/getNBABettingOdds", params={"gameDate": game_date, "playerProps": "true", "itemFormat": "list"})
        response.raise_for_status()
        return response.json()

    def get_team_schedules(self) -> dict:
        response = self.client.get("/getNBATeams", params={"schedules": "true"})
        response.raise_for_status()
        return response.json()

    def get_player_list(self) -> dict:
        response = self.client.get("/getNBAPlayerList")
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self.client.close()


def extract_tank01_stats(box_score_payload: dict) -> dict:
    body = box_score_payload.get("body", box_score_payload)
    result = {"homePts": None, "awayPts": None, "players": {}}
    for key in ("homePts", "awayPts"):
        value = body.get(key)
        if value is not None and str(value).strip().isdigit():
            result[key] = int(value)
    players = body.get("playerStats", {})
    entries = players.values() if isinstance(players, dict) else players
    for player in entries:
        name = player.get("longName")
        if not name:
            continue
        fields = {"PTS": "pts", "REB": "reb", "AST": "ast", "3PM": "tptfgm",
                  "STL": "stl", "BLK": "blk"}
        stats = {}
        for label, field in fields.items():
            value = player.get(field)
            if value is not None and str(value).strip().isdigit():
                stats[label] = int(value)
        if all(key in stats for key in ("PTS", "REB", "AST")):
            stats["PRA"] = stats["PTS"] + stats["REB"] + stats["AST"]
        for label, first, second in (("PTS_AST", "PTS", "AST"), ("PTS_REB", "PTS", "REB"),
                                     ("REB_AST", "REB", "AST"), ("STL_BLK", "STL", "BLK")):
            if first in stats and second in stats:
                stats[label] = stats[first] + stats[second]
        result["players"][normalize_name(name)] = stats
    return result
