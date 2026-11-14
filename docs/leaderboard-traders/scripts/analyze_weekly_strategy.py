"""Reverse-engineer wallet 0xc533...69a9's 5m BTC Up/Down strategy from the weekly fill ledger.

Reads docs/leaderboard-traders/scripts/full-week-trades_dangerously-skip-permissions_2026-11-01_to_2026-11-08.csv
and prints the analysis sections (markdown) used in the report.

Key recovered facts the script relies on:
  - USD_Amount = Shares * Price * (1 + fee), fee per share = 0.07 * p * (1-p) when taker.
  - Zero-fee fills are maker fills; the two never mix inside one transaction hash.
  - REDEEM USD_Amount ~= Shares => winning token, 0 => losing token.
"""

import csv
import os
import sys

import numpy as np
import pandas as pd

csv.field_size_limit(10**9)

DEFAULT_PATH = "data/dangerously-skip-permissions-trades/17_2026-11-01_to_2026-11-08.csv"
# Any ledger can be analysed: pass a .csv argument or set TRADES_CSV.
PATH = (
    next((a for a in sys.argv[1:] if a.lower().endswith(".csv")), None)
    or os.environ.get("TRADES_CSV")
    or DEFAULT_PATH
)
FEE_RATE = 0.07


def md(frame, floatfmt=".4f"):
    """Markdown table without the tabulate dependency."""
    frame = frame.copy()
    for c in frame.columns:
        if pd.api.types.is_float_dtype(frame[c]):
            frame[c] = frame[c].map(lambda v: f"{v:{floatfmt}}")
    head = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    sep = "|" + "|".join("---" for _ in frame.columns) + "|"
    rows = ["| " + " | ".join(str(v) for v in r) + " |" for r in frame.itertuples(index=False)]
    return "\n".join([head, sep] + rows)


def q(series, ps=(0.1, 0.25, 0.5, 0.75, 0.9)):
    return series.quantile(list(ps)).to_dict()


def load():
    df = pd.read_csv(PATH)
    df["ts"] = pd.to_datetime(df["Timestamp_UTC"], utc=True)
    sec = (df["ts"] - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().astype("int64")
    df["epoch"] = sec
    df["open_ts"] = pd.to_numeric(df["Market_Slug"].str.split("-").str[-1], errors="coerce").fillna(0).astype(int)
    df["close_ts"] = df["open_ts"] + 300
    df["secs_before_close"] = df["close_ts"] - df["epoch"]
    df["offset"] = df["epoch"] - df["open_ts"]
    tr = df[df["Type"] == "TRADE"].copy()
    tr["gross"] = tr["Price"] * tr["Shares"]
    tr["fee"] = tr["USD_Amount"] - tr["gross"]
    tr["is_taker"] = tr["fee"] > 1e-9
    rd = df[df["Type"] == "REDEEM"].copy()
    rb = df[df["Type"].astype(str).str.contains("REBATE")].copy()
    return df, tr, rd, rb


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


def section_a(df, tr, rd, rb, m):
    print("\n## A. Integrity & scale\n")
    print(
        f"Rows {len(df):,} | TRADE {len(tr):,} | REDEEM {len(rd):,} | "
        f"MAKER_REBATE {(rb['Type'] == 'MAKER_REBATE').sum()} | TAKER_REBATE {(rb['Type'] == 'TAKER_REBATE').sum()}"
    )
    print(f"Window {df['ts'].min()} -> {df['ts'].max()}")
    print(f"Trade cash out ${tr['USD_Amount'].sum():,.2f}")
    print(f"  of which fee premium ${tr['fee'].sum():,.2f} ({tr['fee'].sum() / tr['gross'].sum() * 100:.2f}% of gross notional)")
    print(f"  gross notional ${tr['gross'].sum():,.2f}")
    print(f"Redeem cash in ${rd['USD_Amount'].sum():,.2f}")
    print(f"Rebates ${rb['USD_Amount'].sum():,.2f}")
    print(f"Net before rebates ${rd['USD_Amount'].sum() - tr['USD_Amount'].sum():,.2f}")
    print(f"Net after rebates ${rd['USD_Amount'].sum() - tr['USD_Amount'].sum() + rb['USD_Amount'].sum():,.2f}")
    print(f"Markets traded {tr['Condition_ID'].nunique():,} | tokens traded {tr['Token_ID'].nunique():,} "
          f"(ratio {tr['Token_ID'].nunique() / tr['Condition_ID'].nunique():.3f})")
    print(f"Markets settled/redeemed {rd['Condition_ID'].nunique():,} | traded but unredeemed {len(set(tr['Condition_ID']) - set(rd['Condition_ID']))}")

    day = (
        tr.groupby(tr["ts"].dt.date)
        .agg(trades=("Price", "size"), markets=("Condition_ID", "nunique"), usd=("USD_Amount", "sum"),
             shares=("Shares", "sum"), med_price=("Price", "median"), med_usd=("USD_Amount", "median"))
        .reset_index()
        .rename(columns={"ts": "utc_day"})
    )
    print("\nPer UTC day:\n")
    print(md(day, ".2f"))

    fpm = m["n_fills"].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9, 0.99])
    print("\nFills per market:\n")
    print(md(fpm.reset_index().rename(columns={"index": "stat", "n_fills": "value"}), ".1f"))

    tr["sec_bucket"] = tr["epoch"]
    peak = tr.groupby("sec_bucket").size().sort_values(ascending=False)
    print(f"\nPeak fills in one second: {peak.iloc[0]} at epoch {peak.index[0]} "
          f"({pd.to_datetime(peak.index[0], unit='s', utc=True)})")
    print(f"Fills outside [0,300] before close: {((tr['secs_before_close'] < 0) | (tr['secs_before_close'] > 300)).sum()}")
    print(f"Duplicate (tx,token,price) rows: {tr.duplicated(['Transaction_Hash', 'Token_ID', 'Price']).sum()}")
    dev = (tr["USD_Amount"] / tr["Shares"] - tr["Price"]).abs()
    print(f"Rows where USD/Shares deviates from Price by >1%: {(dev > 0.01).sum():,} "
          f"(= fee rows; max deviation {dev.max():.4f})")
    print(f"Taker (fee-paying) fills: {tr['is_taker'].mean() * 100:.1f}% of fills, "
          f"{tr.loc[tr['is_taker'], 'USD_Amount'].sum() / tr['USD_Amount'].sum() * 100:.1f}% of cash")
    print(f"Fee paid ${tr['fee'].sum():,.2f}; maker fills pay $0.00")


def section_b(tr, m):
    print("\n## B. Dual-sided inventory\n")
    both = m[m["sh_up"] > 0]
    both = both[both["sh_dn"] > 0]
    print(f"Markets with both sides: {len(both)} / {len(m)} ({len(both) / len(m) * 100:.1f}%)")
    sv = both["sum_vwap"].dropna()
    ai = both["sum_vwap_allin"].dropna()
    print(f"vwap_up+vwap_dn (gross prices): {q(sv)}; mean {sv.mean():.4f}; <1.00 {100 * (sv < 1).mean():.1f}%; >1.00 {100 * (sv > 1).mean():.1f}%")
    print(f"vwap_up+vwap_dn (all-in, fees included): {q(ai)}; mean {ai.mean():.4f}; <1.00 {100 * (ai < 1).mean():.1f}%; >1.00 {100 * (ai > 1).mean():.1f}%")
    print("\nHistogram of all-in vwap_up+vwap_dn:\n")
    edges = [0, 0.85, 0.90, 0.95, 0.98, 1.00, 1.02, 1.05, 1.10, 1.25]
    hist = pd.cut(ai, edges, right=False).value_counts().sort_index()
    h = pd.DataFrame({"bucket": hist.index.astype(str), "markets": hist.values})
    h["share_pct"] = h["markets"] / h["markets"].sum() * 100
    print(md(h, ".2f"))

    mdsh = both["min_sh"].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9])
    ad = both["abs_diff"].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9])
    rel = (both["abs_diff"] / both[["sh_up", "sh_dn"]].max(axis=1)).describe(percentiles=[0.5, 0.75, 0.9])
    print("\nMatched quantity min(shares):\n")
    print(md(mdsh.reset_index().rename(columns={"index": "stat", "min_sh": "value"}), ".2f"))
    print("\nResidual exposure |shares_up-shares_down|:\n")
    print(md(ad.reset_index().rename(columns={"index": "stat", "abs_diff": "value"}), ".2f"))
    print(f"\nRelative imbalance: median {rel.loc['50%'] * 100:.1f}%, p75 {rel.loc['75%'] * 100:.1f}%, p90 {rel.loc['90%'] * 100:.1f}%")

    print("\nPnL decomposition (gross of fees, settled markets only):\n")
    st = m[m["settled"]]
    one_side = st[st["sum_vwap_allin"].isna()]
    two_side = st[st["sum_vwap_allin"].notna()]
    dec = pd.DataFrame(
        {
            "component": ["locked spread capture", "residual directional", "one-sided markets",
                          "gross trading", "fees", "net trading"],
            "usd": [
                two_side["locked"].sum(),
                two_side["residual"].sum(),
                one_side["pnl_gross"].sum(),
                st["pnl_gross"].sum(),
                -st["fees"].sum(),
                st["pnl_net"].sum(),
            ],
        }
    )
    dec["pct_of_gross_notional"] = dec["usd"] / st["gross_cost"].sum() * 10000
    dec["per_market_mean"] = dec["usd"] / len(st)
    print(md(dec, ".2f"))

    print("\nPnL by all-in paired cost bucket (settled markets):\n")
    b = m[m["settled"] & m["sum_vwap_allin"].notna()].copy()
    b["bucket"] = pd.cut(b["sum_vwap_allin"], [0, 0.90, 0.95, 0.98, 1.00, 1.02, 1.05, 1.10, 2.0], right=False)
    bt = b.groupby("bucket", observed=True).agg(markets=("pnl_net", "size"), mean_locked=("locked", "mean"),
                                                mean_residual=("residual", "mean"), mean_net=("pnl_net", "mean"),
                                                total_net=("pnl_net", "sum"), win_pct=("pnl_net", lambda x: (x > 0).mean() * 100))
    bt = bt.reset_index()
    bt["bucket"] = bt["bucket"].astype(str)
    print(md(bt, ".2f"))

    print("\nSecond-side acquisition lag (first fill of each side, seconds):\n")
    lag = (both["first_d"] - both["first_u"]).abs()
    lagd = lag.describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9]).rename("seconds")
    print(md(lagd.reset_index().rename(columns={"index": "stat"}), ".1f"))
    for lo, hi in [(0, 1), (2, 5), (6, 15), (16, 30), (31, 60), (61, 120), (121, 300)]:
        print(f"  {lo}-{hi}s: {100 * ((lag >= lo) & (lag <= hi)).mean():.1f}%")


def section_c(m, rb):
    print("\n## C. PnL attribution\n")
    s = m[m["settled"]]
    print(f"Settled markets {len(s)} of {len(m)}; unresolved {len(m) - len(s)}")
    print(f"Gross trading PnL ${s['pnl_gross'].sum():,.2f} | fees ${-s['fees'].sum():,.2f} | "
          f"net trading ${s['pnl_net'].sum():,.2f} | rebates ${rb['USD_Amount'].sum():,.2f}")
    unresolved = m[m["pnl_gross"].isna()]
    print(f"Reconcile: settled gross cost ${s['gross_cost'].sum():,.2f} + unresolved cash cost "
          f"${unresolved['cost'].sum():,.2f} = ${s['gross_cost'].sum() + unresolved['cost'].sum():,.2f} total cash out"
          f" (gross). Cash net before rebates ${s['pnl_net'].sum() - unresolved['cost'].sum():,.2f}.")
    print(f"Market win rate (net>0): {100 * (s['pnl_net'] > 0).mean():.1f}% | "
          f"median net ${s['pnl_net'].median():.2f} | mean ${s['pnl_net'].mean():.2f}")
    print(f"Token hold win rate: {100 * (m['sh_up'] * (m['winner'] == 'Up') + m['sh_dn'] * (m['winner'] == 'Down')).sum() / (m['sh_up'] + m['sh_dn']).sum():.1f}% "
          "(share-weighted)")

    best = s["pnl_net"].idxmax()
    worst = s["pnl_net"].idxmin()
    print(f"Best market {best}: net ${s.loc[best, 'pnl_net']:.2f}, gross ${s.loc[best, 'pnl_gross']:.2f}, "
          f"vwap_u {s.loc[best, 'vwap_up']:.3f}, vwap_d {s.loc[best, 'vwap_dn']:.3f}, "
          f"sh {s.loc[best, 'sh_up']:.1f}/{s.loc[best, 'sh_dn']:.1f}, winner {s.loc[best, 'winner']}")
    print(f"Worst market {worst}: net ${s.loc[worst, 'pnl_net']:.2f}, gross ${s.loc[worst, 'pnl_gross']:.2f}, "
          f"vwap_u {s.loc[worst, 'vwap_up']:.3f}, vwap_d {s.loc[worst, 'vwap_dn']:.3f}, "
          f"sh {s.loc[worst, 'sh_up']:.1f}/{s.loc[worst, 'sh_dn']:.1f}, winner {s.loc[worst, 'winner']}")

    s = s.copy()
    s["day"] = pd.to_datetime(s["open_ts"], unit="s", utc=True).dt.date
    daily = s.groupby("day").agg(markets=("pnl_net", "size"), gross=("pnl_gross", "sum"),
                                 fees=("fees", "sum"), net=("pnl_net", "sum"),
                                 locked=("locked", "sum"), residual=("residual", "sum"))
    rbd = rb.groupby(rb["ts"].dt.date)["USD_Amount"].sum()
    daily["rebates"] = rbd
    daily["total"] = daily["net"] + daily["rebates"]
    daily["rebates"] = daily["rebates"].fillna(0)
    daily["total"] = daily["net"] + daily["rebates"]
    daily["cum_total"] = daily["total"].cumsum()
    print("\nDaily PnL:\n")
    print(md(daily.reset_index().rename(columns={"day": "utc_day"}), ".2f"))
    eq = daily["total"].fillna(0).cumsum()
    print(f"\nCumulative total end ${eq.iloc[-1]:,.2f}; max drawdown on daily equity ${(eq - eq.cummax()).min():,.2f}")
    meq = s.sort_values("open_ts")["pnl_net"].cumsum()
    print(f"Market-level net equity (fees, no rebates): max drawdown ${(meq - meq.cummax()).min():,.2f}; "
          f"worst point ${meq.min():,.2f}")
    print(f"Per-market gross PnL: mean ${s['pnl_gross'].mean():.2f}, std ${s['pnl_gross'].std():.2f}, "
          f"weekly Sharpe-like t = {s['pnl_gross'].mean() / s['pnl_gross'].std() * np.sqrt(len(s)):.2f}")
    print(f"Per-market residual: mean ${s['residual'].mean():.2f}, std ${s['residual'].std():.2f}, "
          f"t = {s['residual'].mean() / s['residual'].std() * np.sqrt(len(s)):.2f}")
    print(f"Locked share of gross trading PnL: {100 * s['locked'].sum() / s['pnl_gross'].sum():.1f}%")
    print(f"Markets with locked>0: {100 * (s['locked'] > 0).mean():.1f}%; "
          f"mean locked ${s['locked'].mean():.2f}; mean residual ${s['residual'].mean():.2f}")


def section_d(tr, m):
    print("\n## D. Timing fingerprint\n")
    sbc = tr["secs_before_close"]
    print(f"secs_before_close: {q(sbc)}; mean {sbc.mean():.1f}")
    bins = [0, 15, 30, 60, 90, 120, 180, 240, 300]
    c = pd.cut(sbc, bins, right=False)
    tab = tr.groupby(c, observed=True).agg(fills=("Price", "size"), usd=("USD_Amount", "sum"), shares=("Shares", "sum"))
    tab["fill_pct"] = tab["fills"] / tab["fills"].sum() * 100
    tab["usd_pct"] = tab["usd"] / tab["usd"].sum() * 100
    print("\nFills by seconds before close:\n")
    print(md(tab.reset_index().rename(columns={"secs_before_close": "window"}), ".2f"))

    pxb = pd.cut(tr["Price"], [0, 0.2, 0.45, 0.6, 0.8, 1.0], right=False)
    print("\nMedian secs_before_close by price bucket and fill type:\n")
    t = tr.groupby([pxb, "is_taker"], observed=True).agg(n=("Price", "size"), med_sbc=("secs_before_close", "median"),
                                                         med_usd=("USD_Amount", "median")).reset_index()
    t.columns = ["price_bucket", "taker", "fills", "median_sbc", "median_usd"]
    print(md(t, ".1f"))

    m2 = m[m["first_fill"] < 9e17].copy()
    m2["first_off"] = m2["first_fill"] - m2["open_ts"]
    m2["last_off"] = m2["last_fill"] - m2["open_ts"]
    print("\nMarket open offset (first fill) and close offset (last fill), seconds:\n")
    off = pd.DataFrame(
        {
            "stat": ["p10", "p25", "p50", "p75", "p90", "p99", "max"],
            "first_fill_offset": [m2["first_off"].quantile(p) for p in (0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0)],
            "last_fill_offset": [m2["last_off"].quantile(p) for p in (0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0)],
        }
    )
    print(md(off, ".1f"))
    print(f"Markets with a fill in the first 5s: {100 * (m2['first_off'] <= 5).mean():.1f}%; "
          f"first 15s: {100 * (m2['first_off'] <= 15).mean():.1f}%; "
          f"last 15s: {100 * (m2['last_off'] >= 285).mean():.1f}%")


def section_e(tr, m):
    print("\n## E. Price behavior & calibration\n")
    print(f"Fill price: {q(tr['Price'])}; mean {tr['Price'].mean():.4f}")
    for lo, hi in [(0, 0.1), (0.9, 1.01)]:
        sub = tr[(tr["Price"] >= lo) & (tr["Price"] < hi)]
        print(f"Fills at price [{lo},{hi}): {len(sub):,} ({100 * len(sub) / len(tr):.1f}%), "
              f"{sub['USD_Amount'].sum() / tr['USD_Amount'].sum() * 100:.1f}% of cash")

    tr = tr.sort_values(["Condition_ID", "Token_ID", "epoch", "Transaction_Hash", "Price"])
    tr["dpx"] = tr.groupby(["Condition_ID", "Token_ID"])["Price"].diff()
    print(f"\nConsecutive same-token price change: mean {tr['dpx'].mean():+.4f}, "
          f"median {tr['dpx'].median():+.4f}, share down {100 * (tr['dpx'] < 0).mean():.1f}%, "
          f"flat {100 * (tr['dpx'] == 0).mean():.1f}%, up {100 * (tr['dpx'] > 0).mean():.1f}%")

    tok = m.reset_index()
    print("\nFill-level calibration (each fill -> did its token win):\n")
    tr2 = tr.merge(m[["winner"]], left_on="Condition_ID", right_index=True, how="left")
    tr2["won"] = ((tr2["Outcome"] == "Up") & (tr2["winner"] == "Up")) | (
        (tr2["Outcome"] == "Down") & (tr2["winner"] == "Down")
    )
    done = tr2[tr2["winner"].notna()].copy()
    done["pxb"] = pd.cut(done["Price"], [round(0.05 * i, 2) for i in range(21)], right=False)
    done["fill_pnl"] = np.where(done["won"], done["Shares"], 0.0) - done["gross"]
    cal = done.groupby("pxb", observed=True).agg(n=("won", "size"), hit=("won", "mean"),
                                                 avg_px=("Price", "mean"), usd=("USD_Amount", "sum"),
                                                 pnl=("fill_pnl", "sum"))
    cal["hit"] *= 100
    cal["edge_pp"] = cal["hit"] - cal["avg_px"] * 100
    cal["pnl_per_usd_pct"] = cal["pnl"] / cal["usd"] * 100
    cal = cal.reset_index()
    cal["pxb"] = cal["pxb"].astype(str)
    print(md(cal, ".2f"))

    mk = tr[~tr["is_taker"]].groupby(["Condition_ID", "Token_ID"]).apply(
        lambda g: pd.Series({"maker_vwap": (g["Price"] * g["Shares"]).sum() / g["Shares"].sum(), "maker_sh": g["Shares"].sum()}),
        include_groups=False)
    tk = tr[tr["is_taker"]].groupby(["Condition_ID", "Token_ID"]).apply(
        lambda g: pd.Series({"taker_vwap": (g["Price"] * g["Shares"]).sum() / g["Shares"].sum(), "taker_sh": g["Shares"].sum()}),
        include_groups=False)
    joined = mk.join(tk, how="inner")
    print("\nP&L by fill type (gross of fees):\n")
    ft = done.groupby("is_taker").agg(fills=("won", "size"), usd=("USD_Amount", "sum"),
                                      gross_pnl=("fill_pnl", "sum"), hit=("won", "mean"), avg_px=("Price", "mean"))
    ft["bps"] = ft["gross_pnl"] / ft["usd"] * 10000
    ft["hit"] *= 100
    ft = ft.reset_index().rename(columns={"is_taker": "taker"})
    print(md(ft, ".2f"))

    print(f"\nTokens with both maker and taker fills: {len(joined)}; paired maker-vwap minus taker-vwap: "
          f"mean {(joined['maker_vwap'] - joined['taker_vwap']).mean():+.4f}, "
          f"median {(joined['maker_vwap'] - joined['taker_vwap']).median():+.4f}")

    ordered = tr.sort_values(["Condition_ID", "Token_ID", "epoch", "Transaction_Hash", "Price"]).copy()
    ordered["next_px"] = ordered.groupby(["Condition_ID", "Token_ID"])["Price"].shift(-1)
    ordered["next_dt"] = ordered.groupby(["Condition_ID", "Token_ID"])["epoch"].shift(-1) - ordered["epoch"]
    drift = ordered[(ordered["next_dt"] <= 30) & ordered["next_px"].notna()]
    print(f"Next same-token fill within 30s: mean drift maker {(drift.loc[~drift['is_taker'], 'next_px'] - drift.loc[~drift['is_taker'], 'Price']).mean():+.4f}, "
          f"taker {(drift.loc[drift['is_taker'], 'next_px'] - drift.loc[drift['is_taker'], 'Price']).mean():+.4f}")

    print("\nMarginal (directional) fill calibration: each fill that widened the share imbalance:\n")
    ordered = tr.sort_values(["Condition_ID", "epoch", "Transaction_Hash", "Price"]).copy()
    ordered["signed"] = np.where(ordered["Outcome"] == "Up", ordered["Shares"], -ordered["Shares"])
    ordered["net_before"] = ordered.groupby("Condition_ID")["signed"].cumsum() - ordered["signed"]
    ordered["net_after"] = ordered["net_before"] + ordered["signed"]
    ordered["marginal"] = ordered["net_after"].abs() > ordered["net_before"].abs()
    marg = ordered[ordered["marginal"]].merge(
        m[["winner"]], left_on="Condition_ID", right_index=True, how="left"
    )
    marg = marg[marg["winner"].notna()].copy()
    marg["won"] = ((marg["Outcome"] == "Up") & (marg["winner"] == "Up")) | (
        (marg["Outcome"] == "Down") & (marg["winner"] == "Down")
    )
    marg["payoff"] = np.where(marg["won"], marg["Shares"], 0.0)
    marg["pnl"] = marg["payoff"] - marg["gross"]
    marg["pxb"] = pd.cut(marg["Price"], [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], right=False)
    mc = marg.groupby("pxb", observed=True).agg(fills=("won", "size"), hit=("won", "mean"),
                                                avg_px=("Price", "mean"), shares=("Shares", "sum"),
                                                usd=("USD_Amount", "sum"), pnl=("pnl", "sum"))
    mc["hit"] *= 100
    mc["edge_pp"] = mc["hit"] - mc["avg_px"] * 100
    mc["pnl_per_usd_pct"] = mc["pnl"] / mc["usd"] * 100
    mc = mc.reset_index()
    mc["pxb"] = mc["pxb"].astype(str)
    print(md(mc, ".2f"))
    print(f"Marginal fills {len(marg):,} ({100 * len(marg) / len(tr):.1f}% of fills, "
          f"{marg['Shares'].sum() / tr['Shares'].sum() * 100:.1f}% of shares), "
          f"${marg['USD_Amount'].sum():,.0f}, gross PnL ${marg['pnl'].sum():,.2f} "
          f"({marg['pnl'].sum() / marg['USD_Amount'].sum() * 100:.2f}% of cash)")


def section_f(tr, m):
    print("\n## F. Sizing & risk\n")
    print(f"USD per fill: {q(tr['USD_Amount'])}; mean {tr['USD_Amount'].mean():.2f}")
    print(f"Shares per fill: {q(tr['Shares'])}; mean {tr['Shares'].mean():.2f}; "
          f"exactly 30: {100 * (tr['Shares'].round(2) == 30).mean():.1f}%")
    print(f"USD per market: mean ${m['cost'].mean():.2f}, median ${m['cost'].median():.2f}, "
          f"p90 ${m['cost'].quantile(0.9):.2f}, max ${m['cost'].max():.2f}")
    print(f"Shares per market: median {m['sh_up'].add(m['sh_dn']).median():.1f}, max {m['sh_up'].add(m['sh_dn']).max():.1f}")
    print(f"Single-ticket max USD ${tr['USD_Amount'].max():.2f}; single-ticket max shares {tr['Shares'].max():.2f}")

    tr = tr.sort_values(["Condition_ID", "epoch", "Transaction_Hash", "Price"])
    tr["cum_market_usd"] = tr.groupby("Condition_ID")["USD_Amount"].cumsum()
    print(f"Max cumulative cost inside one market: ${tr.groupby('Condition_ID')['USD_Amount'].sum().max():.2f}")

    p = tr.copy()
    p["pxb"] = pd.cut(p["Price"], [0, .2, .4, .6, .8, 1.0], right=False)
    print("\nSize vs price (median shares and USD per fill):\n")
    t = p.groupby("pxb", observed=True).agg(fills=("Shares", "size"), med_shares=("Shares", "median"),
                                            med_usd=("USD_Amount", "median"), med_sbc=("secs_before_close", "median")).reset_index()
    t["pxb"] = t["pxb"].astype(str)
    print(md(t, ".2f"))

    p["timeb"] = pd.cut(p["secs_before_close"], [0, 30, 60, 120, 180, 240, 300], right=False)
    print("\nSize vs time to close:\n")
    t = p.groupby("timeb", observed=True).agg(fills=("Shares", "size"), med_shares=("Shares", "median"),
                                              med_sbc=("secs_before_close", "median"), med_usd=("USD_Amount", "median")).reset_index()
    t["timeb"] = t["timeb"].astype(str)
    print(md(t, ".2f"))

    # martingale: next-market size after a win vs loss
    s = m[m["settled"]].sort_values("open_ts").copy()
    s["prev_net"] = s["pnl_net"].shift(1)
    print(f"\nMean market cost after a winning market ${s.loc[s['prev_net'] > 0, 'cost'].mean():.2f} "
          f"vs after a losing market ${s.loc[s['prev_net'] <= 0, 'cost'].mean():.2f}")

    # concurrency sweep: cash committed to still-open windows
    ev = []
    for _, r in m.iterrows():
        ev.append((r["first_fill"], r["cost"]))
        ev.append((r["last_fill"] + 1, -r["cost"]))
    ev.sort()
    cur = peak = 0.0
    for _, d in ev:
        cur += d
        peak = max(peak, cur)
    print(f"\nPeak concurrent cash committed across overlapping windows: ${peak:,.2f}")
    print(f"Sum of all market cost / markets: ${m['cost'].sum():,.0f} / {len(m)}")
    print("Working bankroll lower bound (peak deployed): see above; turnover/day "
          f"${m['cost'].sum() / 7:,.0f}")


def section_g(tr, m, rb):
    print("\n## G. Regime change\n")
    s = m[m["settled"]].copy()
    s["day"] = pd.to_datetime(s["open_ts"], unit="s", utc=True).dt.date
    tr2 = tr.copy()
    tr2["day"] = tr2["ts"].dt.date
    days = sorted(tr2["day"].unique())
    rows = []
    for d in days:
        t = tr2[tr2["day"] == d]
        mm = s[s["day"] == d]
        rbd = rb[rb["ts"].dt.date == d]["USD_Amount"].sum()
        rows.append(
            {
                "day": str(d),
                "trades": len(t),
                "markets": mm.shape[0],
                "trades_per_mkt": len(t) / max(mm.shape[0], 1),
                "med_fill_usd": t["USD_Amount"].median(),
                "med_price": t["Price"].median(),
                "notional": t["USD_Amount"].sum(),
                "taker_pct": t["is_taker"].mean() * 100,
                "gross_pnl": mm["pnl_gross"].sum(),
                "fees": mm["fees"].sum(),
                "net": mm["pnl_net"].sum(),
                "cost_per_mkt": mm["cost"].mean(),
                "mkt_win_pct": (mm["pnl_net"] > 0).mean() * 100,
                "rebates": rbd,
            }
        )
    r = pd.DataFrame(rows)
    r["total"] = r["net"] + r["rebates"]
    r["gross_bps"] = r["gross_pnl"] / r["notional"] * 10000
    r["net_bps"] = r["net"] / r["notional"] * 10000
    r["rebate_bps"] = r["rebates"] / r["notional"] * 10000
    print(md(r, ".2f"))

    print("\nPhase comparison:\n")
    phases = {"Nov 2-5 (full)": ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"],
              "Nov 6 (decay)": ["2026-11-06"], "Nov 7-8 (low)": ["2026-11-07", "2026-11-08"]}
    out = []
    for name, ds in phases.items():
        x = r[r["day"].isin(ds)]
        out.append({"phase": name, "trades/mkt": x["trades"].sum() / x["markets"].sum(),
                    "med_fill_usd": x["med_fill_usd"].median(), "med_price": x["med_price"].median(),
                    "taker_pct": x["taker_pct"].mean(), "gross_bps": x["gross_bps"].mean(),
                    "net_bps": x["net_bps"].mean(), "rebate_bps": x["rebate_bps"].mean(),
                    "net_per_mkt": x["net"].sum() / x["markets"].sum()})
    print(md(pd.DataFrame(out), ".2f"))


def section_h(tr, m, tok):
    print("\n## H. Within-market replay\n")

    def show(cid, label):
        mm = m.loc[cid]
        t = tr[tr["Condition_ID"] == cid].sort_values(["epoch", "Transaction_Hash", "Price"]).copy()
        t["bucket"] = t["offset"] // 15 * 15
        agg = t.groupby(["bucket", "Outcome"]).agg(n=("Price", "size"), sh=("Shares", "sum"),
                                                   vwap=("gross", "sum")).reset_index()
        agg["vwap"] = agg["vwap"] / agg["sh"]
        print(f"\n### {label} {cid[:10]}... {pd.to_datetime(mm['open_ts'], unit='s', utc=True)}")
        print(f"winner={mm['winner']}, vwap_u={mm['vwap_up']:.3f} sh_u={mm['sh_up']:.1f}, "
              f"vwap_d={mm['vwap_dn']:.3f} sh_d={mm['sh_dn']:.1f}, sum={mm['sum_vwap']:.3f}")
        print(f"locked ${mm['locked']:.2f}, residual ${mm['residual']:.2f}, gross ${mm['pnl_gross']:.2f}, "
              f"fees ${mm['fees']:.2f}, net ${mm['pnl_net']:.2f}")
        print("| off-15s | side | fills | shares | vwap |")
        print("|---|---|---|---|---|")
        for _, r in agg.iterrows():
            print(f"| {int(r['bucket'])} | {r['Outcome']} | {int(r['n'])} | {r['sh']:.0f} | {r['vwap']:.3f} |")

    s = m[m["settled"]]
    show(s["locked"].idxmax(), "Largest locked capture:")
    show(s["locked"].idxmin(), "Worst locked (sum>1):")
    show(s["pnl_net"].idxmax(), "Largest net win:")
    show(s["pnl_net"].idxmin(), "Largest net loss:")
    one = s[(s["sh_up"] > 0) ^ (s["sh_dn"] > 0)]
    if len(one):
        show(one["cost"].idxmax(), "Largest one-sided market:")
    late = s[(s["first_fill"] - s["open_ts"]) > 180]
    if len(late):
        show(late["cost"].idxmax(), "Latest entry:")


def section_i(tr, m, rb):
    print("\n## I. Rebate mechanics\n")
    r = rb.copy()
    r["day"] = r["ts"].dt.date
    piv = r.pivot_table(index="day", columns="Type", values="USD_Amount", aggfunc="sum").fillna(0)
    notional = tr.groupby(tr["ts"].dt.date)["USD_Amount"].sum()
    piv["notional"] = notional
    piv["maker_bps"] = piv["MAKER_REBATE"] / piv["notional"] * 10000
    piv["taker_bps"] = piv["TAKER_REBATE"] / piv["notional"] * 10000
    piv["total_bps"] = (piv["MAKER_REBATE"] + piv["TAKER_REBATE"]) / piv["notional"] * 10000
    print(md(piv.reset_index(), ".2f"))
    print(f"\nTotal rebates ${r['USD_Amount'].sum():,.2f} = "
          f"{r['USD_Amount'].sum() / tr['USD_Amount'].sum() * 10000:.1f} bps of cash notional")
    print(f"Maker ${r.loc[r['Type'] == 'MAKER_REBATE', 'USD_Amount'].sum():,.2f}, "
          f"taker ${r.loc[r['Type'] == 'TAKER_REBATE', 'USD_Amount'].sum():,.2f}")
    print(f"Taker fees embedded in fills ${tr['fee'].sum():,.2f}; rebates cover "
          f"{r['USD_Amount'].sum() / tr['fee'].sum() * 100:.1f}% of them")
    print(f"Marginal rebate per extra $1M of two-sided notional: ~${r['USD_Amount'].sum() / tr['USD_Amount'].sum() * 1e6:,.0f}")


def main():
    df, tr, rd, rb = load()
    tok, m = build_markets(tr, rd)
    print("# Weekly strategy reverse-engineering - computed sections")
    section_a(df, tr, rd, rb, m)
    section_b(tr, m)
    section_c(m, rb)
    section_d(tr, m)
    section_e(tr, m)
    section_f(tr, m)
    section_g(tr, m, rb)
    section_h(tr, m, tok)
    section_i(tr, m, rb)


if __name__ == "__main__":
    main()
