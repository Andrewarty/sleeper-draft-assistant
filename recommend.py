#!/usr/bin/env python3
"""Create live fantasy draft recommendations from Sleeper state + master board.

Decision philosophy:
- Our master board and its tiers are the authority.
- ECR/ADP describe the market; they do not redefine player quality.
- Roster construction, QB timing, tier cliffs and next-pick survival are
  decision modifiers inside the board's tier structure.
"""

import csv
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def norm(name):
    name = (name or "").lower().replace("’", "'")
    name = re.sub(r"\b(jr|sr|ii|iii|iv)\.?\b", "", name)
    name = re.sub(r"[^a-z0-9]", "", name)
    return name


def tier_for(rank):
    if rank <= 6: return 1
    if rank <= 17: return 2
    if rank <= 30: return 3
    if rank <= 45: return 4
    if rank <= 65: return 5
    if rank <= 90: return 6
    if rank <= 125: return 7
    return 8


def next_user_pick(current_pick, slot, teams):
    """Find the next pick after current_pick belonging to this slot in a snake."""
    for p in range(current_pick + 1, current_pick + teams * 3 + 1):
        rnd = (p - 1) // teams + 1
        within = (p - 1) % teams + 1
        pick_slot = within if rnd % 2 == 1 else teams + 1 - within
        if pick_slot == slot:
            return p
    return None


def clamp(value, low, high):
    return max(low, min(high, value))


def survival_label(adp, current_pick, nxt):
    if nxt is None:
        return "unknown"
    if adp <= current_pick + 3:
        return "almost certainly gone"
    if adp <= nxt - 3:
        return "unlikely to make it back"
    if adp <= nxt + 4:
        return "coin flip to return"
    return "good chance to return"


def pick_window(rank, adp, current_pick, nxt, return_risk, board_gap):
    """Translate board + market into a simple live-draft instruction."""
    reach = adp - current_pick

    if board_gap >= 8 and reach >= 12 and return_risk == "good chance to return":
        return "AVOID AT PRICE"
    if return_risk in {"almost certainly gone", "unlikely to make it back"}:
        return "TAKE"
    if return_risk == "coin flip to return":
        return "DO NOT LET PAST TURN"
    if nxt is not None and adp > nxt + 4:
        return "CAN WAIT"
    return "TAKE"


def main():
    state = json.loads((ROOT / "draft_state.json").read_text())
    config = json.loads((ROOT / "draft_config.json").read_text())

    with (ROOT / "master_board.csv").open(newline="") as f:
        board = list(csv.DictReader(f))

    drafted_names = set()
    for p in state.get("picks", []):
        m = p.get("metadata") or {}
        full = f"{m.get('first_name','')} {m.get('last_name','')}".strip()
        drafted_names.add(norm(full))

    my_picks = state.get("my_picks", [])
    roster = []
    for p in my_picks:
        m = p.get("metadata") or {}
        roster.append({
            "name": f"{m.get('first_name','')} {m.get('last_name','')}".strip(),
            "pos": m.get("position", ""),
            "pick": p.get("pick_no")
        })
    counts = Counter(x["pos"] for x in roster)

    current_pick = state.get("next_pick_number", len(state.get("picks", [])) + 1)
    teams = int(state.get("teams") or config.get("league_size") or 12)
    slot = int(state.get("draft_slot") or config.get("draft_slot") or 1)
    rnd = (current_pick - 1) // teams + 1
    nxt = next_user_pick(current_pick, slot, teams)

    available_rows = [row for row in board if norm(row["name"]) not in drafted_names]
    best_available_rank = min((int(row["rank"]) for row in available_rows), default=999)
    best_available_tier = tier_for(best_available_rank)

    candidates = []
    for row in available_rows:
        rank = int(row["rank"])
        adp = float(row["adp"])
        ecr = int(row["ecr"])
        pos = row["pos"]
        tier = tier_for(rank)
        board_gap = rank - best_available_rank

        # MASTER BOARD IS THE BASELINE. Lower is better.
        score = float(rank)

        # Market/ECR is deliberately capped. It can break ties inside our tier,
        # but cannot overpower what our board says about player quality.
        ecr_modifier = clamp((ecr - rank) * 0.12, -2.0, 2.0)
        score += ecr_modifier

        # Roster fit is a nudge, not a license to jump tiers.
        roster_modifier = 0.0
        if pos == "RB" and counts["RB"] == 0:
            roster_modifier -= 1.5
        elif pos == "WR" and counts["WR"] == 0:
            roster_modifier -= 1.5
        elif pos == "TE" and counts["TE"] == 0 and rank <= 35:
            roster_modifier -= 1.0
        elif pos == "TE" and counts["TE"] >= 1:
            roster_modifier += 1.0
        score += roster_modifier

        # 1QB discipline. Elite QBs can still win inside their board tier, but
        # we do not let positional urgency manufacture an early QB reach.
        qb_modifier = 0.0
        if pos == "QB":
            if counts["QB"] >= 1:
                qb_modifier += 5.0
            elif rnd <= 3 and rank > 25:
                qb_modifier += 2.5
            elif rnd <= 4 and rank > 40:
                qb_modifier += 2.0
        score += qb_modifier

        # ADP is market timing only. Reward falls / penalize reaches modestly.
        adp_value = current_pick - adp
        market_modifier = 0.0
        if adp_value >= 12:
            market_modifier -= 1.5
        elif adp_value >= 6:
            market_modifier -= 0.75
        elif adp_value <= -18:
            market_modifier += 1.5
        elif adp_value <= -10:
            market_modifier += 0.75
        score += market_modifier

        return_risk = survival_label(adp, current_pick, nxt)

        candidates.append({
            "name": row["name"],
            "pos": pos,
            "team": row["team"],
            "board_rank": rank,
            "rank": rank,
            "market_ecr": ecr,
            "ecr": ecr,
            "adp": adp,
            "tier": tier,
            "board_gap": board_gap,
            "score": round(score, 2),
            "adp_value": round(adp_value, 1),
            "return_risk": return_risk,
            "modifiers": {
                "ecr": round(ecr_modifier, 2),
                "roster_fit": round(roster_modifier, 2),
                "qb_timing": round(qb_modifier, 2),
                "market_value": round(market_modifier, 2),
            },
        })

    # Tier is an absolute guardrail: no lower-tier player can leapfrog a
    # higher-tier player simply because ADP/ECR/roster modifiers like him.
    candidates.sort(key=lambda x: (x["tier"], x["score"], x["board_rank"]))

    # Add live pick-window labels after sorting so they are easy to consume.
    for c in candidates:
        c["pick_window"] = pick_window(
            c["board_rank"], c["adp"], current_pick, nxt,
            c["return_risk"], c["board_gap"]
        )
        c["tier_cliff"] = c["tier"] == best_available_tier and any(
            other["tier"] > c["tier"] for other in candidates
        )

    top = candidates[:10]

    result = {
        "draft_id": state.get("draft_id"),
        "draft_status": state.get("status"),
        "current_pick": current_pick,
        "round": rnd,
        "draft_slot": slot,
        "next_user_pick": nxt,
        "roster": roster,
        "roster_counts": dict(counts),
        "best_available_board_rank": best_available_rank if best_available_rank != 999 else None,
        "best_available_tier": best_available_tier if best_available_rank != 999 else None,
        "recommendation": top[0] if top else None,
        "next_best": top[1:5],
        "top_10_available": top,
        "logic": "Master board + tiers are authoritative; capped ECR/ADP, roster fit, QB timing and next-pick survival only refine decisions within tiers",
        "board_size": len(board),
    }

    (ROOT / "recommendation.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
