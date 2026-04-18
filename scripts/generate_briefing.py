#!/usr/bin/env python3
"""
Generate daily whale briefing markdown from whale_scanner.py output.
Reads /tmp/whale_data.json, writes briefings/whale-briefing-YYYY-MM-DD.md
"""

import json
import os
import sys
from datetime import datetime

DATE = datetime.now().strftime("%Y-%m-%d")
INPUT = "/tmp/whale_data.json"
OUTPUT = f"briefings/whale-briefing-{DATE}.md"

PRICES = {
    "BTC": None, "ETH": None, "SOL": None, "DOGE": None, "PEPE": None,
    "AVAX": None, "LINK": None, "ARB": None, "SUI": None, "WIF": None,
    "HYPE": None, "INJ": None, "TIA": None,
}


def load_data():
    if not os.path.exists(INPUT):
        sys.exit(f"ERROR: {INPUT} not found. Run whale_scanner.py first.")
    with open(INPUT) as f:
        data = json.load(f)
    if "error" in data:
        sys.exit(f"ERROR: Scanner failed — {data['error']}")
    return data


def build_coin_map(wallets):
    longs, shorts = {}, {}
    entries = {}
    for w in wallets:
        for pos in w.get("positions", []):
            c = pos["coin"]
            if pos["direction"] == "LONG":
                longs[c] = longs.get(c, 0) + 1
                entries.setdefault(c, []).append(float(pos.get("entry_price", 0)))
            else:
                shorts[c] = shorts.get(c, 0) + 1
                entries.setdefault(c, []).append(float(pos.get("entry_price", 0)))
    all_coins = set(list(longs) + list(shorts))
    result = {}
    for c in all_coins:
        l, s = longs.get(c, 0), shorts.get(c, 0)
        t = l + s
        e_list = entries.get(c, [])
        avg_e = round(sum(e_list) / len(e_list), 2) if e_list else 0
        result[c] = {
            "longs": l, "shorts": s, "total": t,
            "long_pct": round(l / t * 100) if t else 0,
            "short_pct": round(s / t * 100) if t else 0,
            "avg_entry": avg_e,
        }
    return result


def signal(long_pct):
    try:
        long_pct = int(long_pct)
    except (TypeError, ValueError):
        return "MIXED"
    if long_pct >= 65:
        return "BULLISH"
    if long_pct <= 35:
        return "BEARISH"
    return "MIXED"


def top_wallets_by_value(wallets, n=5):
    return sorted(wallets, key=lambda w: float(w.get("account_value", 0)), reverse=True)[:n]


def biggest_position(wallet):
    positions = wallet.get("positions", [])
    if not positions:
        return None
    return max(positions, key=lambda p: abs(float(p.get("entry_price", 0)) * float(p.get("size", 0))))


def generate(data):
    top_wallets = data["top_traders"]["wallets"]
    rekt_wallets = data["rekt_traders"]["wallets"]
    top_map = build_coin_map(top_wallets)
    rekt_map = build_coin_map(rekt_wallets)

    all_coins = sorted(
        set(list(top_map) + list(rekt_map)),
        key=lambda c: top_map.get(c, {}).get("total", 0) + rekt_map.get(c, {}).get("total", 0),
        reverse=True
    )

    # ── Top contrarian: biggest smart vs rekt divergence (min 3 traders each side) ──
    best_div, best_contrarian = 0, None
    for c in all_coins:
        t = top_map.get(c, {})
        r = rekt_map.get(c, {})
        if t.get("total", 0) < 3 or r.get("total", 0) < 3:
            continue
        div = abs(t["long_pct"] - r["long_pct"])
        if div > best_div:
            best_div, best_contrarian = div, c

    # ── Highest conviction: smart-money consensus + rekt inversion + position count ──
    best_score, best_trade = 0, None
    for c in all_coins:
        t = top_map.get(c, {})
        r = rekt_map.get(c, {})
        if t.get("total", 0) < 4:
            continue
        smart_bias = t["long_pct"] - 50        # positive = smart longs, negative = smart shorts
        rekt_bias = r.get("long_pct", 50) - 50  # same scale
        # Score highest when smart has strong direction AND rekt is opposite
        inversion_bonus = 1.5 if (smart_bias * rekt_bias < 0) else 1.0
        score = abs(smart_bias) * t["total"] * inversion_bonus
        if score > best_score:
            best_score = score
            direction = "LONG" if smart_bias > 0 else "SHORT"
            best_trade = (c, direction, t, r.get("long_pct", 50), score)

    # ── Notable wallets ──
    notable = top_wallets_by_value(top_wallets)

    # ── Scan stats ──
    top_scan_note = data["top_traders"].get("note", "")
    rekt_scan_note = data["rekt_traders"].get("note", "")
    total_smart_pos = sum(len(w.get("positions", [])) for w in top_wallets)
    total_rekt_pos = sum(len(w.get("positions", [])) for w in rekt_wallets)

    # ── Coin signal label ──
    def coin_signal(t, r):
        ts, rs = signal(t.get("long_pct", 50)), signal(r.get("long_pct", 50))
        if ts == rs:
            return f"{ts} (consensus)"
        if ts != "MIXED":
            return f"{ts} (smart fade)" if rs != "MIXED" else f"{ts} (smart lead)"
        return "MIXED"

    # ── Confidence for best trade ──
    def confidence(score, smart_pct, rekt_pct, wallet_count):
        base = min(score / 150, 4.0)
        div_bonus = min(abs(smart_pct - rekt_pct) / 20, 3.0)
        count_bonus = min(wallet_count / 10, 2.0)
        raw = base + div_bonus + count_bonus
        return min(10, round(raw + 1))

    # ── Entry / SL / TP logic ──
    def trade_levels(token, direction, avg_entry):
        # conservative sizing: 1.5% SL, 3% TP (2:1 RR) for majors; wider for alts
        majors = {"BTC", "ETH", "SOL"}
        sl_pct = 0.015 if token in majors else 0.025
        tp_pct = sl_pct * 2
        entry = avg_entry
        if direction == "LONG":
            sl = round(entry * (1 - sl_pct), 4)
            tp = round(entry * (1 + tp_pct), 4)
        else:
            sl = round(entry * (1 + sl_pct), 4)
            tp = round(entry * (1 - tp_pct), 4)
        # Position size: risk 2% of $1000 = $20 per trade, stop distance in %
        if entry <= 0:
            return 0, 0, 0, 0
        risk_dollars = 20
        position_size_pct = round((risk_dollars / (entry * sl_pct)) / 10 * 100, 1)
        position_size_pct = min(position_size_pct, 20)
        return entry, sl, tp, position_size_pct

    # ── Format currency ──
    def fmt(val):
        if val >= 1000:
            return f"${val:,.2f}"
        elif val >= 1:
            return f"${val:.4f}"
        else:
            return f"${val:.8f}"

    # ── Build markdown ──
    lines = []
    lines.append(f"# 🐋 Hyperliquid Whale Briefing — {DATE}")
    lines.append(f"_Generated at {datetime.now().strftime('%H:%M')} UTC | Top 50 + Rekt 50 wallets scanned_\n")

    # Main assets
    for coin in ["BTC", "ETH", "SOL"]:
        t = top_map.get(coin, {"longs": 0, "shorts": 0, "long_pct": 50, "total": 0, "avg_entry": 0})
        r = rekt_map.get(coin, {"longs": 0, "shorts": 0, "long_pct": 50, "total": 0})
        sig = signal(t["long_pct"])
        if t.get("total", 0) > 0 and r.get("total", 0) > 0:
            div = t["long_pct"] - r["long_pct"]
            if abs(div) > 20:
                if sig == "BULLISH" and div > 0:
                    reasoning = f"Smart money {t['long_pct']}% long vs rekt {r['long_pct']}% long — {abs(div)}pp divergence confirms directional edge."
                elif sig == "BEARISH" and div < 0:
                    reasoning = f"Smart money {t['short_pct']}% short vs rekt {r['long_pct']}% long — {abs(div)}pp divergence; classic fade setup."
                else:
                    reasoning = f"Cross-group divergence of {abs(div)}pp; smart money leads direction."
            else:
                reasoning = f"Both cohorts aligned at {t['long_pct']}%/{r['long_pct']}% long — broad consensus, low fade risk."
        else:
            reasoning = "Insufficient position data."

        lines.append(f"## 🎯 {coin}/USD")
        lines.append(f"- Smart money: {t['longs']} long, {t['shorts']} short ({t['long_pct']}% bullish)")
        lines.append(f"- Rekt money: {r['longs']} long, {r['shorts']} short ({r['long_pct']}% bullish)")
        lines.append(f"- Signal: **{sig}** — {reasoning}")
        lines.append(f"- Avg entry (top traders): {fmt(t['avg_entry'])}\n")

    # Contrarian signal
    if best_contrarian:
        ct = top_map[best_contrarian]
        cr = rekt_map.get(best_contrarian, {"long_pct": 50, "short_pct": 50, "longs": 0, "shorts": 0})
        smart_dir = "LONG" if ct["long_pct"] > 50 else "SHORT"
        lines.append("## ⚡ Top Contrarian Signal\n")
        lines.append(f"**{best_contrarian} — {smart_dir} bias, {best_div}pp confidence gap (widest in scan)**\n")
        lines.append(
            f"Smart money is {ct['long_pct']}% {'long' if smart_dir == 'LONG' else 'short'} on {best_contrarian} "
            f"({ct['longs']}L / {ct['shorts']}S) while rekt traders are {cr['long_pct']}% long "
            f"({cr['longs']}L / {cr['shorts']}S). A {best_div}pp gap is the largest divergence in today's scan. "
            f"Follow smart money: **{smart_dir}**.\n"
        )

    # Full coin breakdown
    lines.append("## 📊 Full Coin Breakdown")
    lines.append("| Coin | Smart Long% | Smart Short% | Rekt Long% | Rekt Short% | Signal |")
    lines.append("|------|-------------|--------------|------------|-------------|--------|")
    EMPTY = {"long_pct": 50, "short_pct": 50, "total": 0, "longs": 0, "shorts": 0}
    for c in all_coins:
        t = top_map.get(c, EMPTY)
        r = rekt_map.get(c, EMPTY)
        sig = coin_signal(t, r) if isinstance(t.get("long_pct"), int) and isinstance(r.get("long_pct"), int) else "-"
        tl = f"{t['long_pct']}%" if t.get("total", 0) > 0 else "—"
        ts_ = f"{t['short_pct']}%" if t.get("total", 0) > 0 else "—"
        rl = f"{r['long_pct']}%" if r.get("total", 0) > 0 else "—"
        rs_ = f"{r['short_pct']}%" if r.get("total", 0) > 0 else "—"
        lines.append(f"| {c} | {tl} | {ts_} | {rl} | {rs_} | {sig} |")
    lines.append("\n_Sorted by total trader count (smart + rekt combined)_\n")

    # Best trade setup
    if best_trade:
        token, direction, t_data, rekt_long_pct, score = best_trade
        avg_e = t_data["avg_entry"]
        entry, sl, tp, pos_size = trade_levels(token, direction, avg_e)
        conf = confidence(score, t_data["long_pct"], rekt_long_pct, t_data["total"])
        smart_pct = t_data["long_pct"] if direction == "LONG" else t_data["short_pct"]
        rekt_opp_pct = (100 - rekt_long_pct) if direction == "LONG" else rekt_long_pct

        lines.append("## 🏆 Highest-Conviction Trade Setup\n")
        lines.append(f"| Field | Value |")
        lines.append(f"|-------|-------|")
        lines.append(f"| **Token** | {token}/USD |")
        lines.append(f"| **Direction** | {direction} |")
        lines.append(f"| **Entry** | {fmt(entry)} |")
        lines.append(f"| **Stop Loss** | {fmt(sl)} |")
        lines.append(f"| **Take Profit** | {fmt(tp)} |")
        lines.append(f"| **Position Size** | {pos_size}% of account (~${pos_size * 10:.0f} on $1,000) |")
        lines.append(f"| **Risk/Reward** | 1:2 |")
        lines.append(f"| **Confidence** | {conf}/10 |\n")
        lines.append(f"**Basis:** {t_data['total']} smart-money wallets in {token}, {smart_pct}% positioned {direction.lower()}. "
                     f"Rekt traders {rekt_opp_pct}% on the other side — a {abs(t_data['long_pct'] - rekt_long_pct)}pp inversion. "
                     f"Risk 2% of account ($20 on $1,000). Only enter on a {fmt(entry)} retest; invalidate and cut if price closes through {fmt(sl)}.\n")

    # Notable wallets
    lines.append("## 📋 Notable Wallets")
    lines.append("| Rank | Address | Account Value | Largest Position |")
    lines.append("|------|---------|--------------|-----------------|")
    for i, w in enumerate(notable, 1):
        addr = w.get("address", "?")
        val = float(w.get("account_value", 0))
        pos = biggest_position(w)
        if pos:
            pos_str = f"{pos['direction']} {pos['coin']} @ {fmt(pos['entry_price'])}"
        else:
            pos_str = "No open positions"
        lines.append(f"| {i} | `{addr}` | ${val:,.0f} | {pos_str} |")

    lines.append("")
    lines.append(f"---")
    lines.append(f"_Scan stats: {top_scan_note} | {rekt_scan_note}_")
    lines.append(f"_Smart positions: {total_smart_pos} · Rekt positions: {total_rekt_pos} · Coins tracked: {len(all_coins)}_")

    return "\n".join(lines)


if __name__ == "__main__":
    data = load_data()
    os.makedirs("briefings", exist_ok=True)
    content = generate(data)
    with open(OUTPUT, "w") as f:
        f.write(content)
    print(f"Written: {OUTPUT}")
