#!/usr/bin/env python3
"""Compute parallel build waves from a unit dependency graph.

Input JSON (file argument or stdin):
  {"edges": [["A", "B"], ...], "nodes": ["A", "B", ...]}
  - "nodes" is optional; any node appearing in an edge is included automatically.
  - Edge ["A", "B"] means: A depends on B  (B must be built before A).

Output: ordered build waves. Units within the same wave have no
inter-dependencies and can be implemented in parallel. A dependency
cycle is reported as an error (a cycle means the decomposition is wrong).

Usage:
  plan_waves.py graph.json
  cat graph.json | plan_waves.py
"""
import json
import sys

USAGE = '{"edges": [["A", "B"], ...], "nodes": ["A", ...]}  (edge [A,B] = A depends on B)'


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    print(f"expected: {USAGE}", file=sys.stderr)
    sys.exit(1)


def load(argv):
    raw = open(argv[1]).read() if len(argv) > 1 else sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        fail(f"invalid JSON: {e}")
    if not isinstance(data, dict):
        fail("top level must be a JSON object")
    raw_edges = data.get("edges", [])
    if not isinstance(raw_edges, list):
        fail('"edges" must be a list of [unit, dependency] pairs')
    edges = []
    for e in raw_edges:
        if not (isinstance(e, list) and len(e) == 2):
            fail(f"each edge must be a [unit, dependency] pair, got: {e!r}")
        edges.append((e[0], e[1]))
    nodes = set(data.get("nodes", []))
    for a, b in edges:
        nodes.add(a)
        nodes.add(b)
    return nodes, edges


def compute_waves(nodes, edges):
    deps = {n: set() for n in nodes}  # n -> set of units n depends on
    for a, b in edges:
        deps[a].add(b)
    done = set()
    remaining = set(nodes)
    out = []
    while remaining:
        ready = sorted(n for n in remaining if deps[n] <= done)
        if not ready:
            return None, remaining  # nothing buildable -> cycle
        out.append(ready)
        done |= set(ready)
        remaining -= set(ready)
    return out, None


def main():
    nodes, edges = load(sys.argv)
    if not nodes:
        fail("no nodes in graph")
    out, blocked = compute_waves(nodes, edges)
    if blocked is not None:
        print("ERROR: dependency cycle — these units are in a cycle or "
              "downstream of one: " + ", ".join(sorted(blocked)), file=sys.stderr)
        sys.exit(1)
    for i, wave in enumerate(out):
        tag = "leaves" if i == 0 else f"wave {i}"
        print(f"{tag} (parallel): {', '.join(wave)}")


if __name__ == "__main__":
    main()
