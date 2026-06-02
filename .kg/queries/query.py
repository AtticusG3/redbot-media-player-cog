#!/usr/bin/env python3
"""Run competency-question queries over .kg JSONL."""

from __future__ import annotations

import json
from pathlib import Path

KG = Path(__file__).resolve().parent.parent


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> None:
    nodes, edges = load(KG / "nodes.jsonl"), load(KG / "edges.jsonl")
    repo_id = "repo:redbot-media-player-cog"
    results = {
        "CQ-01": sorted({n["type"] for n in nodes}),
        "CQ-02": next((n for n in nodes if n["id"] == repo_id), None),
        "CQ-03": [e["to"] for e in edges if e["from"] == repo_id and e["type"] == "CONTAINS"],
        "CQ-04": [n["id"] for n in nodes if n["type"] == "Config"],
        "CQ-05": [e["to"] for e in edges if e["type"] == "DEPENDS_ON"],
        "CQ-06": [n["id"] for n in nodes if n["type"] == "Script"],
        "CQ-07": [n["id"] for n in nodes if n["type"] == "Document"],
    }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
