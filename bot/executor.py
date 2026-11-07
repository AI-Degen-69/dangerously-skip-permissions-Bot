"""Paper executor state machine — reproduces measured timing without keys.

T+3-25s open (first touch median 13s) -> +15s hedge leg -> M1-M3 work
-> M4 snipe (fades: extremes only late) -> hold to redeem. Buy-only,
no sells. Lean tilts clip allocation; dumb lean=0 = even straddle.
"""

from dataclasses import dataclass, field

from . import constants as C
from .risk import RiskState, check_window, clip_shares
from .signal import LeanSignal


@dataclass
class PaperFill:
    minute: int  # M0..M4
    outcome: str  # Up | Down
    price: float
    shares: float
    usd: float


@dataclass
class WindowPlan:
    event_slug: str
    fills: list[PaperFill] = field(default_factory=list)

    @property
    def cost(self) -> float:
        return sum(f.usd for f in self.fills)


def plan_window(event_slug: str, lean: LeanSignal, state: RiskState) -> WindowPlan:
    """Deterministic paper plan matching CSV moments (45 median fills)."""
    # M-shape weights from frozen M_BUCKETS, scaled to median 45 fills
    total = sum(C.M_BUCKETS)
    target = int(C.MEDIAN_TRADES_PER_WINDOW)
    counts = [max(1, round(target * b / total)) for b in C.M_BUCKETS]
    # lean tilts Up share: 0.5 + lean*0.25*confidence
    up_p = 0.5 + lean.lean * 0.25 * (0.5 + 0.5 * lean.confidence)
    plan = WindowPlan(event_slug=event_slug)
    cost = 0.0
    for minute, n in enumerate(counts):
        for i in range(n):
            blocked = check_window(len(plan.fills), cost, state)
            if blocked:
                return plan
            # straddle-plus-lean: alternate with lean bias, extremes only in M4
            base_up = (i + minute) % 2 == 0
            if up_p > 0.6 and i % 3 != 0:
                up_side = True  # lean Up overrides base on 2/3 of fills
            elif up_p < 0.4 and i % 3 != 0:
                up_side = False  # lean Down overrides base on 2/3 of fills
            else:
                up_side = base_up  # straddle base: lean=0 stays even
            outcome = "Up" if up_side else "Down"
            if minute < 4:
                price = 0.476  # first-price mean; mid-window grind
            else:
                price = 0.85 if (i % 5 == 0) else (0.15 if i % 7 == 0 else 0.476)
            shares = clip_shares(C.CLIP_SHARES_DEFAULT if i % 3 == 0 else C.MEDIAN_SHARES)
            usd = round(price * shares, 2)
            plan.fills.append(PaperFill(minute=minute, outcome=outcome, price=price, shares=shares, usd=usd))
            cost += usd
    return plan
