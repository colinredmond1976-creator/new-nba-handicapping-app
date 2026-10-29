from datetime import date

import httpx
import pytest

from nba_handicap.analysis.grader import grade_leg
from nba_handicap.api.bref import BRefBoxScoreClient, normalize_name, parse_box_score_html
from nba_handicap.api.odds import Tank01OddsClient, extract_tank01_stats
from nba_handicap.models.schemas import BetLeg


HTML = '''<table id="line_score"><tbody>
<tr><td data-stat="pts">105</td></tr><tr><td data-stat="pts">110</td></tr>
</tbody></table><table id="box-BOS-game-basic"><tbody><tr>
<th data-stat="player">Luka Dončić</th><td data-stat="pts">28</td>
<td data-stat="trb">10</td><td data-stat="ast">7</td><td data-stat="fg3">3</td>
</tr></tbody></table>'''


def leg(**changes):
    data = dict(leg_id="1", game_id="1", game_date=date(2026, 10, 27),
                matchup="Away at Home", market_type="PLAYER_PROP", player_name="Luka Doncic",
                stat_category="PTS", line=24.5, side="OVER", odds_american=-110,
                implied_prob=0.52, model_prob=0.6, edge=0.08)
    data.update(changes)
    return BetLeg(**data)


def test_normalize_name():
    assert normalize_name("Luka Dončić") == "luka doncic"
    assert normalize_name("Kristaps Porziņģis III") == "kristaps porzingis"
    assert normalize_name("Nikola Jokić Jr.") == "nikola jokic"


def test_source_parsers():
    bref = parse_box_score_html(HTML)
    tank = extract_tank01_stats({"body": {"homePts": "110", "awayPts": "105", "playerStats": {
        "1": {"longName": "Luka Dončić", "pts": "28", "reb": "10", "ast": "7", "tptfgm": "3"}
    }}})
    assert tank == bref
    assert bref["players"]["luka doncic"]["PRA"] == 45
    assert grade_leg(leg(), tank, bref).status == "WON"
    assert grade_leg(leg(), tank, bref).verification_status == "CONFIRMED"


def test_discrepancy_push_and_game_markets():
    tank = parse_box_score_html(HTML)
    bref = parse_box_score_html(HTML)
    bref["players"]["luka doncic"]["REB"] = 9
    graded = grade_leg(leg(stat_category="REB", line=9.5), tank, bref)
    assert (graded.status, graded.verification_status) == ("WON", "DISCREPANCY")
    assert grade_leg(leg(line=28), tank, bref).status == "PUSH"
    assert grade_leg(leg(market_type="SPREAD", side="HOME", line=-4.5), tank, bref).status == "WON"
    assert grade_leg(leg(market_type="SPREAD", side="AWAY", line=5), tank, bref).status == "PUSH"
    assert grade_leg(leg(market_type="TOTAL", side="UNDER", line=216), tank, bref).status == "WON"
    assert grade_leg(leg(market_type="MONEYLINE", side="AWAY"), tank, bref).status == "LOST"
    missing = grade_leg(leg(), {}, bref)
    assert (missing.status, missing.verification_status) == ("PENDING", "DISCREPANCY")


def test_clients_without_network(monkeypatch):
    monkeypatch.setenv("RAPIDAPI_HOST", "example.test")
    monkeypatch.setenv("NBA_TANK01_RAPIDAPI_KEY", "test")
    client = Tank01OddsClient()
    client.client.close()
    client.client = httpx.Client(base_url="https://example.test", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"gameID": request.url.params["gameID"]})
    ))
    assert client.get_box_score("game-1") == {"gameID": "game-1"}
    client.close()
    with pytest.raises(ValueError):
        BRefBoxScoreClient(min_interval_sec=3)


@pytest.mark.parametrize('category,expected', [
    ('PTS_AST', 35), ('PTS_REB', 38), ('REB_AST', 17),
    ('STL', 2), ('BLK', 1), ('STL_BLK', 3),
])
def test_combined_and_defensive_props_grade_from_both_sources(category, expected):
    html = HTML.replace('</tr></tbody></table>',
                        '<td data-stat="stl">2</td><td data-stat="blk">1</td></tr></tbody></table>')
    tank = extract_tank01_stats({'body': {'playerStats': {'1': {
        'longName': 'Luka Dončić', 'pts': '28', 'reb': '10', 'ast': '7',
        'tptfgm': '3', 'stl': '2', 'blk': '1',
    }}}})
    bref = parse_box_score_html(html)
    graded = grade_leg(leg(stat_category=category, line=expected - 0.5), tank, bref)
    assert graded.tank01_actual == expected
    assert graded.bref_actual == expected
    assert graded.status == 'WON'
    assert graded.verification_status == 'CONFIRMED'


def test_partial_box_scores_preserve_available_stats():
    html = HTML.replace('<td data-stat="fg3">3</td>', '')
    bref = parse_box_score_html(html)
    graded = grade_leg(leg(), {'players': {'luka doncic': {'PTS': 28}}}, bref)
    assert graded.status == 'WON'
    assert graded.verification_status == 'CONFIRMED'
    assert '3PM' not in bref['players']['luka doncic']


@pytest.mark.parametrize("reason", ["Did Not Play", "Did Not Dress", "Not With Team"])
def test_explicit_non_participation_is_void(reason):
    html = f'''<table id="box-BOS-game-basic"><tbody><tr>
    <th data-stat="player">Luka Dončić</th><td data-stat="reason">{reason}</td>
    </tr></tbody></table>'''
    bref = parse_box_score_html(html)
    graded = grade_leg(leg(), {"players": {}}, bref)
    assert (graded.status, graded.verification_status) == ("VOID", "UNVERIFIED")
    assert graded.tank01_actual is None and graded.bref_actual is None
    conflict = grade_leg(leg(), {"players": {"luka doncic": {"PTS": 28}}}, bref)
    assert (conflict.status, conflict.verification_status) == ("WON", "DISCREPANCY")
    missing = grade_leg(leg(), {"players": {}}, {"players": {}})
    assert (missing.status, missing.verification_status) == ("PENDING", "DISCREPANCY")
