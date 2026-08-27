#!/usr/bin/env python3
"""Create live fantasy draft recommendations from Sleeper state + master board."""

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
    # Find the next pick number belonging to this draft slot in a snake draft.
    for p in range(current_pick + 1, current_pick + teams * 3 + 1):
        rnd = (p - 1) // teams + 1
        within = (p - 1) % teams + 1
        pick_slot = within if rnd % 2 == 1 else teams + 1 - within
        if pick_slot == slot:
            return p
    return None


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

    candidates = []
    for row in board:
        if norm(row["name"]) in drafted_names:
            continue
        rank = int(row["rank"])
        adp = float(row["adp"])
        ecr = int(row["ecr"])
        pos = row["pos"]

        # Lower score is better. Base blends our curated seed rank with ECR.
        score = rank * 0.65 + ecr * 0.35

        # Roster construction for standard 1QB / 2RB / 2WR / 1TE / flex PPR.
        if pos == "RB" and counts["RB"] == 0:
            score -= 4.0
        elif pos == "WR" and counts["WR"] == 0:
            score -= 4.0
        elif pos == "TE" and counts["TE"] == 0 and rank <= 35:
            score -= 2.0

        # In 1QB, avoid forcing QB too early unless truly elite/value.
        if pos == "QB":
            if counts["QB"] >= 1:
                score += 18.0
            elif rnd <= 3 and rank > 25:
                score += 7.0
            elif rnd <= 4 and rank > 40:
                score += 5.0

        # Reward players who have fallen versus ADP; avoid extreme reaches.
        value = current_pick - adp
        if value >= 12:
            score -= 4.0
        elif value >= 6:
            score -= 2.0
        elif value <= -18:
            score += 5.0
        elif value <= -10:
            score += 2.5

        return_risk = "unknown"
        if nxt is not None:
            if adp <= current_pick + 3:
                return_risk = "almost certainly gone"
            elif adp <= nxt - 3:
                return_risk = "unlikely to make it back"
            elif adp <= nxt + 4:
                return_risk = "coin flip to return"
            else:
                return_risk = "good chance to return"

        candidates.append({
            "name": row["name"],
            "pos": pos,
            "team": row["team"],
            "rank": rank,
            "ecr": ecr,
            "adp": adp,
            "tier": tier_for(rank),
            "score": round(score, 2),
            "adp_value": round(value, 1),
            "return_risk": return_risk,
        })

    candidates.sort(key=lambda x: (x["score"], x["rank"]))
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
        "recommendation": top[0] if top else None,
        "next_best": top[1:5],
        "top_10_available": top,
        "logic": "65% curated board + 35% ECR, then roster need, ADP value, QB timing and return-risk adjustments",
        "board_size": len(board),
    }

    (ROOT / "recommendation.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
