# Ownership — whaletrax-kai (public satellite)

Mirrors the canonical note on private `whaletrax`. **No deletes; no wholesale fork merges** from this doc alone.

## Recommendation

| Repo | Visibility | Role |
|------|------------|------|
| [`jmiaie/whaletrax`](https://github.com/jmiaie/whaletrax) | private | **Canonical** WhaleTrax product |
| [`jmiaie/whaletrax_private`](https://github.com/jmiaie/whaletrax_private) | private | Older / alternate private tree — diff before cherry-picks |
| **`jmiaie/whaletrax-kai` (this repo)** | public | Kai satellite — experiments / June QC gate line |
| [`jmiaie/polyshark-ops-kai`](https://github.com/jmiaie/polyshark-ops-kai) | public | Ops / card-spec KB companion (not scanner runtime) |

## Cousin (keep separate)

| Repo | Notes |
|------|--------|
| [`jmiaie/btrax`](https://github.com/jmiaie/btrax) | Separate Polymarket wallet + Whop extract — do not fold in |

## Decision guide

1. **New product features / shared smoke tests** → `jmiaie/whaletrax`  
2. **Kai-only experiments** → may stay on this fork; document drift in PRs  
3. **Fix found only here** → cherry-pick to canonical after diff; never merge the fork wholesale  
4. Ownership remains: private canonical = `whaletrax`, this repo = satellite until Jeff reassigns
