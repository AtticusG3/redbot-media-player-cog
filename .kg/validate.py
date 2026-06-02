#!/usr/bin/env python3
"""Validate .kg/nodes.jsonl and edges.jsonl against schema constraints."""

from __future__ import annotations

import json
import sys
from pathlib import Path

KG_DIR = Path(__file__).resolve().parent
ALLOWED_EDGE_TYPES = {
    "CONTAINS"
}
REQUIRED_NODE_FIELDS = {"id", "type", "source", "extracted_at"}
REQUIRED_EDGE_FIELDS = {"from", "to", "type", "source", "extracted_at"}


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def main() -> int:
    nodes = load_jsonl(KG_DIR / "nodes.jsonl")
    edges = load_jsonl(KG_DIR / "edges.jsonl")
    violations: list[dict] = []
    node_ids: set[str] = set()
    for node in nodes:
        missing = REQUIRED_NODE_FIELDS - node.keys()
        if missing:
            violations.append({"rule": "structural", "entity": node.get("id"), "detail": str(sorted(missing))})
            continue
        if node["id"] in node_ids:
            violations.append({"rule": "unique_node_id", "entity": node["id"], "detail": "duplicate"})
        node_ids.add(node["id"])
    for edge in edges:
        missing = REQUIRED_EDGE_FIELDS - edge.keys()
        if missing:
            violations.append({"rule": "structural", "detail": str(sorted(missing))})
            continue
        if edge["type"] not in ALLOWED_EDGE_TYPES:
            violations.append({"rule": "predicate_in_schema", "entity": edge["type"]})
        if edge["from"] not in node_ids:
            violations.append({"rule": "edge_endpoints_exist", "entity": edge["from"]})
        if edge["to"] not in node_ids:
            violations.append({"rule": "edge_endpoints_exist", "entity": edge["to"]})
    print(f"nodes: {len(nodes)} edges: {len(edges)} violations: {len(violations)}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
