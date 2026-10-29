import math

from nba_handicap.api.bref import normalize_name
from nba_handicap.models.schemas import BetLeg, LegStatus, MarketType, Side, VerificationStatus


def _actual(leg: BetLeg, data: dict) -> float | None:
    if leg.market_type == MarketType.PLAYER_PROP:
        if not leg.player_name or not leg.stat_category:
            return None
        return data.get("players", {}).get(normalize_name(leg.player_name), {}).get(leg.stat_category.value)
    home, away = data.get("homePts"), data.get("awayPts")
    if home is None or away is None:
        return None
    if leg.market_type == MarketType.TOTAL:
        return home + away
    return home - away if leg.side == Side.HOME else away - home


def grade_leg(leg: BetLeg, tank01_data: dict, bref_data: dict) -> BetLeg:
    allowed = {
        MarketType.PLAYER_PROP: (Side.OVER, Side.UNDER),
        MarketType.TOTAL: (Side.OVER, Side.UNDER),
        MarketType.SPREAD: (Side.HOME, Side.AWAY),
        MarketType.MONEYLINE: (Side.HOME, Side.AWAY),
    }
    if leg.side not in allowed[leg.market_type]:
        raise ValueError("Side is not valid for the market")
    tank, bref = _actual(leg, tank01_data), _actual(leg, bref_data)
    if (leg.market_type == MarketType.PLAYER_PROP and leg.player_name
            and normalize_name(leg.player_name) in bref_data.get("did_not_play", [])
            and not tank01_data.get("players", {}).get(normalize_name(leg.player_name))):
        return leg.model_copy(update={
            "tank01_actual": None, "bref_actual": None,
            "verification_status": VerificationStatus.UNVERIFIED, "status": LegStatus.VOID,
        })
    confirmed = tank is not None and bref is not None and math.isclose(tank, bref, rel_tol=0, abs_tol=1e-5)
    verification = VerificationStatus.CONFIRMED if confirmed else VerificationStatus.DISCREPANCY
    status = LegStatus.PENDING
    if tank is not None:
        if leg.market_type == MarketType.SPREAD:
            difference = tank + leg.line
        elif leg.market_type == MarketType.MONEYLINE:
            difference = tank
        else:
            difference = tank - leg.line
            if leg.side == Side.UNDER:
                difference = -difference
        if math.isclose(difference, 0, rel_tol=0, abs_tol=1e-5):
            status = LegStatus.PUSH
        else:
            status = LegStatus.WON if difference > 0 else LegStatus.LOST
    return leg.model_copy(update={
        "tank01_actual": tank, "bref_actual": bref,
        "verification_status": verification, "status": status,
    })
