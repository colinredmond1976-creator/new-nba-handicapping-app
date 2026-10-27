import math
from datetime import date

from nba_handicap.api.bref import normalize_name
from nba_handicap.models.schemas import BetLeg, GameCard, MarketType


def american_to_implied_prob(odds: int) -> float:
    if odds == 0:
        raise ValueError("American odds cannot be zero")
    return -odds / (-odds + 100) if odds < 0 else 100 / (odds + 100)


def american_to_decimal(odds: int) -> float:
    return 1 / american_to_implied_prob(odds)


def calculate_ev(model_prob: float, odds: int) -> float:
    if not math.isfinite(model_prob) or not 0 <= model_prob <= 1:
        raise ValueError("Model probability must be between 0 and 1")
    return model_prob * american_to_decimal(odds) - 1


def score_candidate(leg: BetLeg) -> float:
    if not -220 <= leg.odds_american <= 180 or leg.odds_american == 0:
        return float("-inf")
    if leg.model_prob < 0.54:
        return float("-inf")
    ev = calculate_ev(leg.model_prob, leg.odds_american)
    edge = leg.model_prob - american_to_implied_prob(leg.odds_american)
    bonus = 0.025 if leg.market_type == MarketType.PLAYER_PROP else 0
    return 0.65 * leg.model_prob + 0.25 * edge + 0.10 * ev + bonus


def select_four_legs_for_game(game_id: str, game_date: str, away_team: str,
                              home_team: str, candidates: list[BetLeg]) -> GameCard:
    day = date.fromisoformat(game_date)
    ranked = sorted(candidates, key=score_candidate, reverse=True)
    selected = []
    used = set()
    ids = set()
    for leg in ranked:
        if score_candidate(leg) == float("-inf") or leg.game_id != game_id or leg.game_date != day:
            continue
        if leg.market_type == MarketType.PLAYER_PROP:
            if not leg.player_name or not leg.stat_category:
                continue
            key = (normalize_name(leg.player_name), leg.stat_category)
        else:
            key = (leg.market_type,)
        if key in used or leg.leg_id in ids:
            continue
        implied = american_to_implied_prob(leg.odds_american)
        selected.append(leg.model_copy(update={"implied_prob": implied, "edge": leg.model_prob - implied}))
        used.add(key)
        ids.add(leg.leg_id)
        if len(selected) == 4:
            break
    if len(selected) != 4:
        raise ValueError(f"Fewer than four eligible unique legs for game {game_id}")
    return GameCard(game_id=game_id, game_date=day, away_team=away_team,
                    home_team=home_team, legs=selected)
