"""FastBox delivery simulator.

Loads warehouses, agents and packages from JSON, assigns each package to the
nearest agent, and computes how far each agent travels.
"""

import argparse
import json
import math
import sys
from numbers import Real


def _parse_point(value, what):
    """Return value as an (x, y) float tuple, or raise ValueError.

    bool is a subclass of int in Python, so it is rejected explicitly;
    otherwise [true, false] would quietly become (1.0, 0.0).
    """
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(v, Real) and not isinstance(v, bool) for v in value)
    ):
        raise ValueError(f"{what}: expected [x, y] with two numbers, got {value!r}")
    return (float(value[0]), float(value[1]))


def _parse_locations(raw, kind):
    """Normalize warehouses or agents into {id: (x, y)}.

    Accepts both input formats: a dict {"W1": [x, y]} or a list
    [{"id": "W1", "location": [x, y]}]. A plain dict keeps insertion order,
    which the tie-break rules depend on.
    """
    if isinstance(raw, dict):
        # json.load keeps only the last copy of a duplicate key, so
        # duplicates in dict form cannot be detected here.
        items = list(raw.items())
    elif isinstance(raw, list):
        try:
            items = [(entry["id"], entry["location"]) for entry in raw]
        except (TypeError, KeyError) as exc:
            raise ValueError(f"{kind}: each entry needs 'id' and 'location'") from exc
    else:
        raise ValueError(f"{kind}: expected an object or a list")

    result = {}
    for item_id, location in items:
        if item_id in result:
            raise ValueError(f"{kind}: duplicate id {item_id!r}")
        result[item_id] = _parse_point(location, f"{kind} {item_id!r}")
    return result


def load_data(path):
    """Read an input file and return (warehouses, agents, packages).

    warehouses and agents are {id: (x, y)}, and packages is a list of dicts
    with keys id, warehouse and destination. Input order is kept everywhere
    because ties are broken by input order. Raises ValueError on bad input.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("top level must be a JSON object")
    for key in ("warehouses", "agents", "packages"):
        if key not in data:
            raise ValueError(f"missing top-level key {key!r}")

    warehouses = _parse_locations(data["warehouses"], "warehouse")
    agents = _parse_locations(data["agents"], "agent")

    if not isinstance(data["packages"], list):
        raise ValueError("packages: expected a list")
    packages = []
    seen = set()
    for raw in data["packages"]:
        if not isinstance(raw, dict) or "id" not in raw or "destination" not in raw:
            raise ValueError(f"package entry needs 'id' and 'destination': {raw!r}")
        pid = raw["id"]
        # The dict format uses "warehouse" and the list format uses "warehouse_id".
        wid = raw.get("warehouse", raw.get("warehouse_id"))
        if pid in seen:
            raise ValueError(f"package: duplicate id {pid!r}")
        if wid not in warehouses:
            raise ValueError(f"package {pid!r}: unknown warehouse {wid!r}")
        seen.add(pid)
        packages.append({
            "id": pid,
            "warehouse": wid,
            "destination": _parse_point(raw["destination"], f"package {pid!r}"),
        })

    if packages and not agents:
        raise ValueError("there are packages but no agents to deliver them")
    return warehouses, agents, packages


def distance(a, b):
    """Return the straight-line distance between points a and b."""
    # Euclidean distance: sqrt((x2 - x1)^2 + (y2 - y1)^2).
    return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)


def assign_packages(warehouses, agents, packages):
    """Map every agent id to its list of packages.

    A package goes to the agent whose start point is closest to the package's
    warehouse, since that agent reaches the pickup first. Every agent gets a
    key, even with no packages, so the report always lists every agent.
    """
    assignments = {agent_id: [] for agent_id in agents}
    for pkg in packages:
        origin = warehouses[pkg["warehouse"]]
        best_id, best_dist = None, math.inf
        # Strict < with agents in input order: on a tie the earlier agent wins.
        for agent_id, start in agents.items():
            d = distance(start, origin)
            if d < best_dist:
                best_id, best_dist = agent_id, d
        assignments[best_id].append(pkg)
    return assignments


def simulate(warehouses, agents, assignments):
    """Walk each agent through its deliveries and record the path.

    Returns {agent_id: {"route", "delivered", "total_distance"}}. An agent
    with nothing to deliver stays at its start with distance 0.

    Routing is batched and nearest-first: go to the nearest warehouse that
    still holds this agent's packages, pick up all of them there (capacity
    is unlimited), and drop them off nearest destination first. Picking up
    the whole batch at once avoids returning to the same warehouse. There
    is no return trip at the end.
    """
    results = {}
    for agent_id, start in agents.items():
        position = start
        route = [start]
        delivered = []
        total = 0.0  # accumulated at full precision; rounding happens in the report
        pending = list(assignments.get(agent_id, []))  # already in input order

        while pending:
            # Group pending packages by warehouse. dict order is the order in
            # which each warehouse's first pending package appears in the
            # input, so strict < below breaks ties by input order.
            by_warehouse = {}
            for pkg in pending:
                by_warehouse.setdefault(pkg["warehouse"], []).append(pkg)

            best_wid, best_dist = None, math.inf
            for wid in by_warehouse:
                d = distance(position, warehouses[wid])
                if d < best_dist:
                    best_wid, best_dist = wid, d

            # Travel to the warehouse and pick up everything waiting there.
            position = warehouses[best_wid]
            total += best_dist
            route.append(position)
            batch = by_warehouse[best_wid]
            pending = [p for p in pending if p["warehouse"] != best_wid]

            # Nearest-neighbour drop-off. min() returns the first minimum,
            # so ties go to the package that came first in the input.
            while batch:
                nxt = min(batch, key=lambda p: distance(position, p["destination"]))
                total += distance(position, nxt["destination"])
                position = nxt["destination"]
                route.append(position)
                delivered.append(nxt["id"])
                batch.remove(nxt)

        results[agent_id] = {"route": route, "delivered": delivered, "total_distance": total}
    return results


def build_report(results, total_packages):
    """Build the report dict: one entry per agent plus "best_agent".

    Efficiency is distance per package, so lower is better. Agents with no
    deliveries have efficiency None and cannot be best. Ties go to the agent
    with more deliveries, then to input order. The comparison uses unrounded
    values so rounding cannot create or hide a tie.
    """
    report = {}
    best_id, best_key = None, None
    for index, (agent_id, res) in enumerate(results.items()):
        count = len(res["delivered"])
        dist = res["total_distance"]
        eff = dist / count if count else None
        report[agent_id] = {
            "packages_delivered": count,
            "total_distance": round(dist, 2),
            "efficiency": round(eff, 2) if eff is not None else None,
            "delivered_packages": list(res["delivered"]),
        }
        if eff is not None:
            # Tuples compare element by element: efficiency, then more
            # deliveries (hence -count), then input position.
            key = (eff, -count, index)
            if best_key is None or key < best_key:
                best_id, best_key = agent_id, key

    # Every package must be delivered exactly once; anything else is a bug.
    delivered_total = sum(r["packages_delivered"] for r in report.values())
    if delivered_total != total_packages:
        raise RuntimeError(
            f"delivered {delivered_total} packages but input has {total_packages}"
        )

    report["best_agent"] = best_id
    return report


def main():
    """CLI entry point: simulate one input file and write a JSON report."""
    parser = argparse.ArgumentParser(description="FastBox delivery simulator")
    parser.add_argument("input", nargs="?", default="data.json", help="input JSON file")
    parser.add_argument("-o", "--output", default="report.json", help="report file to write")
    args = parser.parse_args()

    try:
        warehouses, agents, packages = load_data(args.input)
    except (ValueError, FileNotFoundError) as exc:
        # json.JSONDecodeError is a subclass of ValueError, so this catches it too.
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    assignments = assign_packages(warehouses, agents, packages)
    results = simulate(warehouses, agents, assignments)
    report = build_report(results, len(packages))

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    for agent_id in agents:
        r = report[agent_id]
        eff = f"{r['efficiency']:.2f}" if r["efficiency"] is not None else "n/a"
        print(f"{agent_id}: {r['packages_delivered']} delivered {r['delivered_packages']}, "
              f"distance {r['total_distance']:.2f}, efficiency {eff}")
    print(f"Best agent: {report['best_agent']}")
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
