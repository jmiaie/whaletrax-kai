#!/usr/bin/env python3
"""Rank Polymarket traders by frequency (volume) + win rate composite score."""
import json, math

# Leaderboard data extracted from polymarket.com/leaderboard __NEXT_DATA__
# Fields: leaderboard_rank, display_rank, pnl, volume, address
LEADERBOARD = [
    (1,  1,  6864456,   30376203, "0x492442eab586f242b53bda933fd5de859c8a3782", "0x492442...(top holder)"),
    (2,  2,  4016108,          0, "0x02227b8f5a9636e895607edd3185ed6ee5598ff7", "HorizonSplendidView"),
    (3,  3,  3742635,          0, "0xefbc5fec8d7b0acdc8911bdd9a98d6964308f9a2", "reachingsky"),
    (4,  1,  3070747,  132506421, "0x2a2c53bd278c04da9962fcf96490e17f3dfb9bc1", "0x2a2C53bD...(high vol)"),
    (5,  5,  2667527,   14455277, "0xc2e7800b5af46e6093872b177b7a5e7f0563be51", "beachboy4"),
    (6,  6,  2416975,          0, "0x019782cab5d844f02bafb71f512758be78579f3c", "majorexploiter"),
    (7,  2,  2160316,  110840876, "0x2005d16a84ceefa912d4e380cd32e7ff827875ea", "RN1"),
    (8, 16,  2021026,   48263040, "0xead152b855effa6b5b5837f53b24c0756830c76a", "elkmonkey"),
    (9, 14,  1976493,   49733468, "0xee613b3fc183ee44f9da9c05f53e2da107e3debf", "sovereign2013"),
    (10,10,  1918871,   61537554, "0x37c1874a60d348903594a96703e0507c518fc53a", "CemeterySun"),
    (11, 7,  1729021,   72121709, "0x204f72f35326db932158cba6adff0b9a1da95e14", "swisstony"),
    (12,13,  1598556,   18577929, "0x36a3f17401e395ef4cb1b7f42bcdb8ab8e15fafb", "gfjoigfsjoigsjoi"),
    (13,14,  1592465,   10510683, "0x777d9f00c2b4f7b829c9de0049ca3e707db05143", "CarlosMC"),
    (14,20,  1495977,          0, "0xdc876e6873772d38716fda7f2452a78d426d7ab6", "432614799197"),
    (15,16,  1456139,         20, "0xf195721ad850377c96cd634457c70cd9e8308057", "lo34567Taipe"),
    (16,17,  1334603,    9861882, "0x93abbc022ce98d6f45d4444b594791cc4b7a9723", "gatorr"),
    (17,18,  1326760,   16282325, "0xc8075693f48668a264b9fa313b47f52712fcc12b", "texaskid"),
    (18,19,  1292740,   22871931, "0x9f2fe025f84839ca81dd8e0338892605702d2ca8", "surfandturf"),
    (19,20,  1202927,          0, "0x59a0744db1f39ff3afccd175f80e6e8dfc239a09", "Blessed-Sunshine"),
    (20,16,  1167819,    495236, "0x8f037a2e4fd49d11267f4ab874ab7ba745ac64d6", "Anointed-Connect"),
    (21, 6,   912475,   73043804, "0x507e52ef684ca2dd91f90a9d26d149dd3288beae", "GamblingIsAllYouNeed"),
    (22,17,   513587,   45298187, "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30", "Bonereaper"),
    (23,19,   507933,   43127863, "0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82", "anon-1772479215461"),
    (24,18,   127995,   43425100, "0x2785e7022dc20757108204b13c08cea8613b70ae", "poorsob"),
    (25, 5,   112622,   74052406, "0xfe787d2da716d60e8acff57fb87eb13cd4d10319", "ferrariChampions2026"),
    (26,12,    92154,   53374587, "0xd99f3bec8e060ada0aef0c4057695dd5bc22fcdc", "BakerMcKenzie"),
    (27, 9,    91522,   61874764, "0x2663daca3cecf3767ca1c3b126002a8578a8ed1f", "Q96s3kwozynxpau"),
    (28,11,    76006,   54552076, "0xc21ea96be762bb55041529af6e386e7c53b80215", "Just2SeeULaugh"),
    (29, 4,    35724,   74366520, "0x43e98f912cd6ddadaad88d3297e78c0648e688e5", "ashash111"),
    (30, 3,    30382,   90874390, "0x6480542954b70a674a74bd1a6015dec362dc8dc5", "tripping"),
    (31, 8,     7674,   68085482, "0x9e9c8b080659b08c3474ea761790a20982e26421", "meetgoodlife"),
    (32,20,   -177755,   43121558, "0xc8ab97a9089a9ff7e6ef0688e6e591a066946418", "ArmageddonRewardsBilly"),
    (33,13,   -19429,   49930459, "0x5d58e38cd0a7e6f5fa67b7f9c2f70dd70df09a15", "gloriafoster"),
]

ranked = []
for lb_rank, disp_rank, pnl, volume, addr, name in LEADERBOARD:
    volume = float(volume)
    pnl = float(pnl)
    roi = (pnl / volume * 100) if volume > 0 else 0
    freq_score = math.log10(volume + 1) if volume > 0 else 0
    # Composite: high frequency + profitable = best
    # Penalize losers
    composite = freq_score * (1 if pnl > 0 else -0.5)
    
    ranked.append({
        'lb_rank':     lb_rank,
        'name':        name,
        'address':     addr,
        'pnl':         pnl,
        'volume':      volume,
        'roi':         round(roi, 2),
        'freq_score':  round(freq_score, 2),
        'composite':   round(composite, 2),
    })

# Sort by composite descending (freq + profitability)
ranked.sort(key=lambda x: x['composite'], reverse=True)

print("Top 30 Polymarket Traders — Ranked by Frequency+Profitability Composite")
print("=" * 90)
print(f"{'#':>2s}  {'Name':28s}  {'PnL':>12s}  {'Volume':>14s}  {'ROI%':>7s}  {'Freq':>5s}  {'Score':>6s}")
print("-" * 90)
for i, w in enumerate(ranked[:30], 1):
    vol_str = f"${w['volume']:>13,.0f}" if w['volume'] > 0 else "     n/a"
    roi_str = f"{w['roi']:>6.1f}%" if w['volume'] > 0 else "   n/a"
    print(f" {i:2d}  {w['name'][:28]:28s}  ${w['pnl']:>12,.0f}  {vol_str}  {roi_str}  {w['freq_score']:>5.2f}  {w['composite']:>6.2f}")

print()
print("Sorted by: composite score (freq_score x profitability direction)")
print("  = log10(volume+1) for frequency  x  sign(pnl) for profitability")
print()
print("NOTE: Win rate requires Dune Analytics Pro — public Polymarket API only shows PnL + Volume")

# Save ranked results
output = {
    "generated_utc": "2026-04-23T04:01:00Z",
    "source": "polymarket.com/leaderboard __NEXT_DATA__",
    "method": "Composite score = log10(volume+1) x sign(pnl) — freq from volume proxy",
    "note": "Win rate not available via public API — requires Dune Pro or Nansen",
    "wallets": ranked[:30]
}
with open("/home/ubuntu/.openclaw/workspace/repos/whaletrax/leaderboard_ranked.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"\nSaved top 30 to leaderboard_ranked.json")
