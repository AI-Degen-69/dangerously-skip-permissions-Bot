import csv
import os
import pathlib
import sys
import numpy as np
import pandas as pd
def q(series, ps=(0.1, 0.25, 0.5, 0.75, 0.9)):
    return series.quantile(list(ps)).to_dict()
def split_thirds(days):
    """Three equal-length phases of a sorted day list."""
    n = len(days)
    cuts = [0, n // 3, 2 * n // 3, n]
    return [days[a:b] for a, b in zip(cuts, cuts[1:])]
def build_markets(tr, rd):
    tok = (
        tr.groupby(["Condition_ID", "Outcome", "Token_ID"])
        .agg(
            shares=("Shares", "sum"),
            cost=("USD_Amount", "sum"),
            gross=("gross", "sum"),
            fee=("fee", "sum"),
            n=("Price", "size"),
            first=("epoch", "min"),
            last=("epoch", "max"),
            minpx=("Price", "min"),
            maxpx=("Price", "max"),
            taker_sh=("Shares", lambda s: s[tr.loc[s.index, "is_taker"]].sum()),
            open_ts=("open_ts", "first"),
        )
        .reset_index()
    )
    tok["vwap"] = tok["gross"] / tok["shares"]
    tok["taker_frac"] = tok["taker_sh"] / tok["shares"]

    winners = (
        rd.assign(win=rd["USD_Amount"] > 0.5)
        .groupby(["Condition_ID", "Outcome"])
        .agg(win=("win", "max"), redeem_cash=("USD_Amount", "sum"), redeem_sh=("Shares", "sum"))
        .reset_index()
    )
    winner = winners[winners["win"]].set_index("Condition_ID")["Outcome"]

    up = tok[tok["Outcome"] == "Up"].set_index("Condition_ID")
    dn = tok[tok["Outcome"] == "Down"].set_index("Condition_ID")
    m = up.join(dn, lsuffix="_u", rsuffix="_d", how="outer").fillna(0.0)
    m["winner"] = winner
    m["settled"] = m.index.isin(winner.index)
    m["open_ts"] = m["open_ts_u"].where(m["open_ts_u"] > 0, m["open_ts_d"])
    m["sh_up"], m["sh_dn"] = m["shares_u"], m["shares_d"]
    m["vwap_up"] = m["vwap_u"].where(m["shares_u"] > 0)
    m["vwap_dn"] = m["vwap_d"].where(m["shares_d"] > 0)
    m["sum_vwap"] = m["vwap_up"] + m["vwap_dn"]
    m["vwap_up_allin"] = m["cost_u"] / m["sh_up"].where(m["sh_up"] > 0)
    m["vwap_dn_allin"] = m["cost_d"] / m["sh_dn"].where(m["sh_dn"] > 0)
    m["sum_vwap_allin"] = m["vwap_up_allin"] + m["vwap_dn_allin"]
    m["min_sh"] = np.minimum(m["sh_up"], m["sh_dn"])
    m["abs_diff"] = (m["sh_up"] - m["sh_dn"]).abs()
    m["cost"] = m["cost_u"] + m["cost_d"]
    m["gross_cost"] = m["gross_u"] + m["gross_d"]
    m["fees"] = m["fee_u"] + m["fee_d"]
    payout = np.select([m["winner"] == "Up", m["winner"] == "Down"], [m["sh_up"], m["sh_dn"]], default=0.0)
    m["payout"] = np.where(m["settled"], payout, np.nan)
    m["pnl_gross"] = m["payout"] - (m["sh_up"] * m["vwap_up"].fillna(0) + m["sh_dn"] * m["vwap_dn"].fillna(0))
    m["pnl_net"] = m["pnl_gross"] - m["fees"]
    m["locked"] = m["min_sh"] * (1 - m["sum_vwap"])
    m["residual"] = m["pnl_gross"] - m["locked"]
    m["n_fills"] = m["n_u"] + m["n_d"]
    m["first_fill"] = np.minimum(m["first_u"].replace(0, 9e18), m["first_d"].replace(0, 9e18))
    m["last_fill"] = np.maximum(m["last_u"], m["last_d"])
    return tok, m
