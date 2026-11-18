"""Pure pricing math for the executor (fees, fill USD, pair-cost projection)."""

from dataclasses import dataclass

from bot import constants as C


def taker_fee_per_share(price: float, coeff: float = C.TAKER_FEE_COEFF) -> float:
    """Polymarket parabolic taker fee: fee_per_share = coeff * p * (1 - p)."""
    if price <= 0.0 or price >= 1.0 or coeff <= 0.0:
        return 0.0
    return coeff * price * (1.0 - price)


def compute_fill_usd(
    shares: float,
    price: float,
    role: str = "MAKER",
    include_fee: bool = True,
) -> tuple[float, float]:
    """Return (total_usd, fee_usd) for a fill.

    Maker fills (0% fee): USD_Amount = round(shares * price, 2).
    Taker fills: USD_Amount = round(shares * (price + coeff * p * (1 - p)), 2).
    """
    if role == "TAKER" and include_fee:
        fee_ps = taker_fee_per_share(price)
        fee_usd = round(shares * fee_ps, 4)
        total_usd = round(shares * (price + fee_ps), 2)
        return total_usd, fee_usd
    return round(shares * price, 2), 0.0


@dataclass
class MicrostructureDecision:
    action: str  # "fill" | "skip"
    outcome: str | None = None
    price: float | None = None
    shares: float = 0.0
    role: str = "MAKER"  # "MAKER" | "TAKER"
    reason: str = "clip-fill"
    sub_reason: str = "maker-dip-ladder"
    projected_pair_cost: float | None = None
    share_deficit: float = 0.0


def _avg_cost(shares: float, cost: float) -> float | None:
    return (cost / shares) if shares > 0 else None


def _projected_pair_cost(
    inv: dict[str, dict[str, float]],
    side: str,
    add_shares: float,
    add_cost: float,
) -> float | None:
    opp = "Down" if side == "Up" else "Up"
    opp_avg = _avg_cost(inv[opp]["shares"], inv[opp]["cost"])
    new_side_avg = _avg_cost(inv[side]["shares"] + add_shares, inv[side]["cost"] + add_cost)
    if opp_avg is None or new_side_avg is None:
        return None
    return round(new_side_avg + opp_avg, 4)
