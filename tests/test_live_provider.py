import httpx
import pytest

from nba_handicap.api.bref import BRefBoxScoreClient, build_bref_boxscore_url


@pytest.mark.parametrize("team,expected", [
    ("BOS", "BOS"), ("BKN", "BRK"), ("PHX", "PHO"), ("CHA", "CHO"),
])
def test_build_bref_boxscore_url(team, expected):
    assert build_bref_boxscore_url("20261027", team) == (
        f"https://www.basketball-reference.com/boxscores/202610270{expected}.html"
    )


def test_fetch_and_parse_box_score_without_network():
    client = BRefBoxScoreClient()
    client.client.close()
    seen = []

    def respond(request):
        seen.append(str(request.url))
        return httpx.Response(200, text='<table id="line_score"><tbody><tr>'
                              '<td data-stat="pts">100</td></tr><tr>'
                              '<td data-stat="pts">110</td></tr></tbody></table>')

    client.client = httpx.Client(transport=httpx.MockTransport(respond))
    try:
        result = client.fetch_and_parse_box_score("20261027", "BKN")
        assert result["awayPts"] == 100
        assert result["homePts"] == 110
        assert seen == ["https://www.basketball-reference.com/boxscores/202610270BRK.html"]
    finally:
        client.close()


def test_live_provider_with_supplied_payload_shape():
    from nba_handicap.analysis.selector import american_to_implied_prob, select_four_legs_for_game
    from nba_handicap.api.live_provider import Tank01CandidateProvider

    game = {
        "gameID": "20261027_BKN@BOS", "gameDate": "20261027",
        "awayTeam": "BKN", "homeTeam": "BOS",
        "playerProps": [
            {"playerID": str(n), "propBets": {
                "pts": "26.5", "ptsOver": "-140", "ptsUnder": "105",
                "ptsrebast": "42.5", "ptsrebastOver": "-120", "ptsrebastUnder": "-110",
                "threes": "3.5", "threesOver": "135", "threesUnder": "-180",
            }} for n in range(4)
        ],
        "sportsBooks": [
            {"sportsBook": "fanduel", "odds": {"awayTeamSpread": "+11.5",
                "awayTeamSpreadOdds": "-105", "homeTeamSpread": "-11.5",
                "homeTeamSpreadOdds": "-115", "totalOver": "222.5", "totalOverOdds": "-110",
                "totalUnder": "222.5", "totalUnderOdds": "-110", "awayTeamML": "+410", "homeTeamML": "-550"}},
            {"sportsBook": "bet365", "odds": {"awayTeamSpread": "+11.5",
                "awayTeamSpreadOdds": "-109", "homeTeamSpread": "-11.5",
                "homeTeamSpreadOdds": "-111", "totalOver": "222.5", "totalOverOdds": "-112",
                "totalUnder": "222.5", "totalUnderOdds": "-108", "awayTeamML": "+425", "homeTeamML": "-575"}},
        ],
    }

    class Client:
        def get_betting_odds(self, day):
            assert day == "20261027"
            return {"statusCode": 200, "body": [game]}

        def get_player_list(self):
            return {"statusCode": 200, "body": [
                {"playerID": str(n), "longName": f"Player {n}"} for n in range(4)
            ]}

    result = Tank01CandidateProvider(Client())("2026-10-27")[0]
    legs = result["candidates"]
    assert {leg.market_type.value for leg in legs} == {"PLAYER_PROP", "SPREAD", "TOTAL", "MONEYLINE"}
    assert {leg.stat_category.value for leg in legs if leg.stat_category} == {"PTS", "PRA", "3PM"}
    prop = next(leg for leg in legs if leg.player_name == "Player 0" and leg.stat_category == "PTS" and leg.side == "OVER")
    over, under = american_to_implied_prob(-140), american_to_implied_prob(105)
    assert prop.model_prob == pytest.approx(over / (over + under))
    spread = next(leg for leg in legs if leg.market_type == "SPREAD" and leg.side == "HOME")
    assert spread.odds_american == -115
    a, b = american_to_implied_prob(-115), american_to_implied_prob(-105)
    c, d = american_to_implied_prob(-111), american_to_implied_prob(-109)
    assert spread.model_prob == pytest.approx((a / (a + b) + c / (c + d)) / 2)
    card = select_four_legs_for_game(result["game_id"], "2026-10-27", "BKN", "BOS", legs)
    assert len(card.legs) == 4
    books = game.pop("sportsBooks")
    game.update({book["sportsBook"]: book["odds"] for book in books})
    direct = Tank01CandidateProvider(Client())("2026-10-27")[0]["candidates"]
    direct_spread = next(leg for leg in direct if leg.market_type == "SPREAD" and leg.side == "HOME")
    assert direct_spread.odds_american == spread.odds_american
    assert direct_spread.model_prob == pytest.approx(spread.model_prob)


def test_bref_game_id_resolver():
    from nba_handicap.api.bref import resolve_bref_boxscore_url

    assert resolve_bref_boxscore_url("20261027_DET@NY").endswith("202610270NYK.html")
    with pytest.raises(ValueError):
        resolve_bref_boxscore_url("invalid")


def test_all_supplied_two_sided_prop_categories_are_candidates():
    from nba_handicap.api.live_provider import Tank01CandidateProvider

    markets = {}
    for field in ('pts', 'reb', 'ast', 'ptsast', 'ptsreb', 'rebast', 'ptsrebast', 'threes', 'stl', 'blk', 'stlblk'):
        markets.update({field: '1.5', field + 'Over': '-110', field + 'Under': '-110'})
    game = {'gameID': '20261027_BKN@BOS', 'gameDate': '20261027', 'awayTeam': 'BKN',
            'homeTeam': 'BOS', 'playerProps': [{'playerID': '1', 'propBets': markets}]}

    class Client:
        def get_betting_odds(self, day):
            return {'body': [game]}

        def get_player_list(self):
            return {'body': [{'playerID': '1', 'longName': 'Player'}]}

    legs = Tank01CandidateProvider(Client())('2026-10-27')[0]['candidates']
    assert {leg.stat_category.value for leg in legs} == {
        'PTS', 'REB', 'AST', 'PRA', '3PM', 'PTS_AST', 'PTS_REB', 'REB_AST', 'STL', 'BLK', 'STL_BLK',
    }
    assert len(legs) == 22
