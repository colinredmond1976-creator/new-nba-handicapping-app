import re
import threading
import time
import unicodedata
from datetime import datetime

import httpx
from bs4 import BeautifulSoup, Comment

BREF_TEAM_MAP = {
    "BKN": "BRK", "CHA": "CHO", "PHX": "PHO", "GS": "GSW",
    "NY": "NYK", "NO": "NOP", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS",
}


def build_bref_boxscore_url(game_date: str, home_team_abbr: str) -> str:
    if len(game_date) != 8 or not game_date.isascii() or not game_date.isdigit():
        raise ValueError("game_date must be YYYYMMDD")
    datetime.strptime(game_date, "%Y%m%d")
    team = home_team_abbr.upper()
    if not team.isascii() or not team.isalpha():
        raise ValueError("home_team_abbr must contain only letters")
    team = BREF_TEAM_MAP.get(team, team)
    return f"https://www.basketball-reference.com/boxscores/{game_date}0{team}.html"


def resolve_bref_boxscore_url(game_id: str) -> str:
    match = re.fullmatch(r"(\d{8})_([A-Za-z]+)@([A-Za-z]+)", game_id)
    if not match:
        raise ValueError(f"Unsupported Tank01 game ID: {game_id}")
    return build_bref_boxscore_url(match.group(1), match.group(3))


def normalize_name(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = "".join(char for char in name if not unicodedata.combining(char)).lower()
    name = re.sub(r"\s+(?:jr|sr|ii|iii|iv|v)\.?$", "", name.strip())
    return " ".join(name.split())


def parse_box_score_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        if "<table" in comment:
            comment.replace_with(BeautifulSoup(str(comment), "html.parser"))
    result = {"homePts": None, "awayPts": None, "players": {}}
    line_score = soup.select_one("table#line_score")
    if line_score:
        rows = line_score.select("tbody tr")
        scores = []
        for row in rows:
            cell = row.select_one('[data-stat="pts"]') or row.select_one('[data-stat="T"]')
            if cell and cell.get_text(strip=True).isdigit():
                scores.append(int(cell.get_text(strip=True)))
        if len(scores) == 2:
            result["awayPts"], result["homePts"] = scores
    for table in soup.select('table[id^="box-"][id$="-game-basic"]'):
        for row in table.select("tbody tr"):
            player = row.select_one('[data-stat="player"]')
            if not player:
                continue
            reason = row.select_one('td[data-stat="reason"]')
            if reason and reason.get_text(strip=True).lower() in ("did not play", "did not dress", "not with team"):
                result.setdefault("did_not_play", []).append(normalize_name(player.get_text(strip=True)))
                continue
            cells = {key: row.select_one(f'td[data-stat="{source}"]') for key, source in
                     (("PTS", "pts"), ("REB", "trb"), ("AST", "ast"), ("3PM", "fg3"))}
            stats = {key: int(cell.get_text(strip=True)) for key, cell in cells.items()
                     if cell and cell.get_text(strip=True).isdigit()}
            if all(key in stats for key in ("PTS", "REB", "AST")):
                stats["PRA"] = stats["PTS"] + stats["REB"] + stats["AST"]
            for label, source in (("STL", "stl"), ("BLK", "blk")):
                cell = row.select_one(f'td[data-stat="{source}"]')
                if cell and cell.get_text(strip=True).isdigit():
                    stats[label] = int(cell.get_text(strip=True))
            for label, first, second in (("PTS_AST", "PTS", "AST"), ("PTS_REB", "PTS", "REB"),
                                         ("REB_AST", "REB", "AST"), ("STL_BLK", "STL", "BLK")):
                if first in stats and second in stats:
                    stats[label] = stats[first] + stats[second]
            result["players"][normalize_name(player.get_text(strip=True))] = stats
    return result


class BRefBoxScoreClient:
    def __init__(self, min_interval_sec: float = 3.5) -> None:
        if min_interval_sec < 3.5:
            raise ValueError("The minimum request interval is 3.5 seconds")
        self.min_interval_sec = min_interval_sec
        self._last_request = None
        self._lock = threading.Lock()
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)

    def get_box_score(self, url: str) -> dict:
        with self._lock:
            if self._last_request is not None:
                delay = self.min_interval_sec - (time.monotonic() - self._last_request)
                if delay > 0:
                    time.sleep(delay)
            self._last_request = time.monotonic()
            response = self.client.get(url)
        response.raise_for_status()
        return parse_box_score_html(response.text)

    def fetch_and_parse_box_score(self, game_date: str, home_team_abbr: str) -> dict:
        return self.get_box_score(build_bref_boxscore_url(game_date, home_team_abbr))

    def close(self) -> None:
        self.client.close()
