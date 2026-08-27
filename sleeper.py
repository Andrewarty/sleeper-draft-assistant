#!/usr/bin/env python3
"""Pull live draft state from Sleeper's public API.

Usage:
    python sleeper.py
    python sleeper.py <draft_id>

No Sleeper login or API key is required for public draft data.
"""

import json
import sys
import urllib.request
from pathlib import Path

BASE = "https://api.sleeper.app/v1"
ROOT = Path(__file__).resolve().parent


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sleeper-draft-assistant/1.0"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def main():
    config = json.loads((ROOT / "draft_config.json").read_text())
    draft_id = sys.argv[1] if len(sys.argv) > 1 else config["active_draft_id"]

    draft = get_json(f"{BASE}/draft/{draft_id}")
    picks = get_json(f"{BASE}/draft/{draft_id}/picks")

    drafted_player_ids = [p.get("player_id") for p in picks if p.get("player_id")]
    my_picks = [p for p in picks if p.get("draft_slot") == config.get("draft_slot")]

    state = {
        "draft_id": str(draft_id),
        "status": draft.get("status"),
        "type": draft.get("type"),
        "rounds": draft.get("settings", {}).get("rounds"),
        "teams": draft.get("settings", {}).get("teams"),
        "draft_slot": config.get("draft_slot"),
        "pick_count": len(picks),
        "next_pick_number": len(picks) + 1,
        "drafted_player_ids": drafted_player_ids,
        "my_picks": my_picks,
        "picks": picks,
    }

    out = ROOT / "draft_state.json"
    out.write_text(json.dumps(state, indent=2))
    print(json.dumps(state, indent=2))
    print(f"\nSaved live state to {out.name}")


if __name__ == "__main__":
    main()
