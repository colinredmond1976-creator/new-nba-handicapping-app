from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class MarketType(str, Enum):
    PLAYER_PROP = "PLAYER_PROP"
    SPREAD = "SPREAD"
    TOTAL = "TOTAL"
    MONEYLINE = "MONEYLINE"


class StatCategory(str, Enum):
    PTS = "PTS"
    REB = "REB"
    AST = "AST"
    PRA = "PRA"
    THREE_PM = "3PM"
    POINTS_ASSISTS = "PTS_AST"
    POINTS_REBOUNDS = "PTS_REB"
    REBOUNDS_ASSISTS = "REB_AST"
    STEALS = "STL"
    BLOCKS = "BLK"
    STEALS_BLOCKS = "STL_BLK"


class Side(str, Enum):
    OVER = "OVER"
    UNDER = "UNDER"
    HOME = "HOME"
    AWAY = "AWAY"


class LegStatus(str, Enum):
    PENDING = "PENDING"
    WON = "WON"
    LOST = "LOST"
    PUSH = "PUSH"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    CONFIRMED = "CONFIRMED"
    DISCREPANCY = "DISCREPANCY"


class RunStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class BetLeg(BaseModel):
    leg_id: str
    game_id: str
    game_date: date
    matchup: str
    market_type: MarketType
    player_name: str | None = None
    stat_category: StatCategory | None = None
    line: float
    side: Side
    odds_american: int
    implied_prob: float
    model_prob: float
    edge: float
    status: LegStatus = LegStatus.PENDING
    tank01_actual: float | None = None
    bref_actual: float | None = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED


class GameCard(BaseModel):
    game_id: str
    game_date: date
    away_team: str
    home_team: str
    legs: list[BetLeg] = Field(min_length=4, max_length=4)


class RunHeartbeat(BaseModel):
    run_id: str
    timestamp_utc: datetime
    status: RunStatus
    games_processed: int
    legs_graded: int
    discrepancies_flagged: int
    message: str


class PerformanceSummary(BaseModel):
    total_picks: int
    wins: int
    losses: int
    pushes: int
    win_rate: float
    net_units: float
    roi_pct: float


class DashboardPayload(BaseModel):
    heartbeat: RunHeartbeat
    summary: PerformanceSummary
    todays_cards: list[GameCard]
    history: list[BetLeg]
