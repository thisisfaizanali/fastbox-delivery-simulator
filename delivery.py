"""FastBox delivery simulator.

Loads warehouses, agents and packages from JSON, assigns each package to the
nearest agent, and computes how far each agent travels.
"""

import argparse
import json
import math
import random
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
        # json.load accepts NaN and Infinity, which would break every distance.
        or not all(math.isfinite(v) for v in value)
    ):
        raise ValueError(f"{what}: expected [x, y] with two finite numbers, got {value!r}")
    return (float(value[0]), float(value[1]))


def _parse_locations(raw, kind):
    """Normalize warehouses or agents into {id: (x, y)}.

    Accepts both input formats: a dict {"W1": [x, y]} or a list
    [{"id": "W1", "location": [x, y]}]. A plain dict keeps insertion order,
    which the tie-break rules depend on.
    """
    if isinstance(raw, dict):
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


def _reject_duplicate_keys(pairs):
    """object_pairs_hook for json.load that raises on a repeated key.

    By default json.load keeps only the last copy of a repeated key, so a
    duplicate warehouse or agent in dict form would be lost without an error.
    """
    keys = set()
    for key, _ in pairs:
        if key in keys:
            raise ValueError(f"duplicate key {key!r} in input")
        keys.add(key)
    return dict(pairs)


def load_data(path):
    """Read an input file and return (warehouses, agents, packages).

    warehouses and agents are {id: (x, y)}, and packages is a list of dicts
    with keys id, warehouse and destination. Input order is kept everywhere
    because ties are broken by input order. Raises ValueError on bad input.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f, object_pairs_hook=_reject_duplicate_keys)

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


def simulate(warehouses, agents, assignments, seed=None, start_times=None):
    """Walk each agent through its deliveries and record the path.

    Returns {agent_id: {"route", "delivered", "total_distance", "dispatches",
    "finish_time", "total_delay"}}. An agent with nothing to deliver stays at
    its start with distance 0.

    Time: agents move 1 distance unit per minute and the day starts at
    minute 0, unless start_times gives a later start (a late agent). With a
    seed, each drop-off adds a random 0-10 minute delay (traffic, customer
    not home). Delays add time but never distance.

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
        clock = (start_times or {}).get(agent_id, 0.0)
        total_delay = 0.0
        dispatches = []

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

            # Record when the agent leaves for this batch; add_late_agent uses
            # it to tell which batches have not left yet.
            dispatches.append({
                "minute": clock,
                "warehouse": best_wid,
                "packages": [p["id"] for p in by_warehouse[best_wid]],
            })

            # Travel to the warehouse and pick up everything waiting there.
            position = warehouses[best_wid]
            total += best_dist
            clock += best_dist
            route.append(position)
            batch = by_warehouse[best_wid]
            pending = [p for p in pending if p["warehouse"] != best_wid]

            # Nearest-neighbour drop-off. min() returns the first minimum,
            # so ties go to the package that came first in the input.
            while batch:
                nxt = min(batch, key=lambda p: distance(position, p["destination"]))
                leg = distance(position, nxt["destination"])
                total += leg
                clock += leg
                if seed is not None:
                    # Seeded by seed + agent + package rather than one shared
                    # RNG, so a package's delay stays the same when agents are
                    # re-simulated (e.g. after a late agent joins).
                    delay = random.Random(f"{seed}:{agent_id}:{nxt['id']}").uniform(0, 10)
                    clock += delay
                    total_delay += delay
                position = nxt["destination"]
                route.append(position)
                delivered.append(nxt["id"])
                batch.remove(nxt)

        results[agent_id] = {
            "route": route,
            "delivered": delivered,
            "total_distance": total,
            "dispatches": dispatches,
            "finish_time": clock,
            "total_delay": total_delay,
        }
    return results


def add_late_agent(warehouses, agents, packages, assignments, results,
                   late_id, late_loc, join_minute, seed):
    """Add an agent who joins at join_minute and re-simulate the day.

    Batches that have not been dispatched yet (dispatch minute >= join_minute)
    can move to the late agent, using the same nearest-agent rule as
    assign_packages. Returns (agents2, assignments2, results2).
    """
    if late_id in agents:
        raise ValueError(f"late agent id {late_id!r} already exists")
    if join_minute < 0:
        raise ValueError(f"join minute must be >= 0, got {join_minute}")

    waiting = {
        pid
        for res in results.values()
        for d in res["dispatches"]
        if d["minute"] >= join_minute
        for pid in d["packages"]
    }
    owner = {p["id"]: agent_id for agent_id, pkgs in assignments.items() for p in pkgs}

    # Limitation: heuristic. It compares start locations, as the spec's
    # assignment rule does, not where agents actually are at join_minute.
    # The upgrade path is a dispatcher that uses live positions and
    # re-optimises routes.
    moved = set()
    for pkg in packages:
        if pkg["id"] in waiting:
            origin = warehouses[pkg["warehouse"]]
            if distance(late_loc, origin) < distance(agents[owner[pkg["id"]]], origin):
                moved.add(pkg["id"])

    agents2 = {**agents, late_id: late_loc}  # appended last, so listed last in the report
    # Only packages that had not left yet are removed, so each original
    # agent's earlier dispatches come out the same when re-simulated.
    assignments2 = {
        agent_id: [p for p in pkgs if p["id"] not in moved]
        for agent_id, pkgs in assignments.items()
    }
    assignments2[late_id] = [p for p in packages if p["id"] in moved]  # input order
    results2 = simulate(warehouses, agents2, assignments2, seed=seed,
                        start_times={late_id: join_minute})
    return agents2, assignments2, results2


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
    parser.add_argument("--delays", action="store_true", help="add random 0-10 minute delays per delivery")
    parser.add_argument("--seed", type=int, default=42, help="seed for --delays (default 42)")
    parser.add_argument("--late-agent", nargs=4, metavar=("ID", "X", "Y", "MINUTE"),
                        help="an agent who starts at (X, Y) at MINUTE")
    args = parser.parse_args()

    # Seed only with --delays: simulate treats seed=None as "no delays".
    seed = args.seed if args.delays else None
    late_id = None
    try:
        warehouses, agents, packages = load_data(args.input)
        assignments = assign_packages(warehouses, agents, packages)
        results = simulate(warehouses, agents, assignments, seed=seed)
        if args.late_agent:
            late_id = args.late_agent[0]
            x, y, join_minute = (float(v) for v in args.late_agent[1:])
            if not all(math.isfinite(v) for v in (x, y, join_minute)):
                raise ValueError("--late-agent X, Y and MINUTE must be finite numbers")
            agents, assignments, results = add_late_agent(
                warehouses, agents, packages, assignments, results,
                late_id, (x, y), join_minute, seed,
            )
    except (ValueError, OSError) as exc:
        # OSError covers a missing file, a directory path and permission errors.
        # json.JSONDecodeError is a subclass of ValueError, so this catches it too.
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    report = build_report(results, len(packages))
    # Time fields are added only when asked for, so the default report is unchanged.
    timed = args.delays or late_id is not None
    if timed:
        for agent_id, res in results.items():
            report[agent_id]["finish_time_minutes"] = round(res["finish_time"], 2)
            if args.delays:
                report[agent_id]["total_delay_minutes"] = round(res["total_delay"], 2)
        if late_id is not None:
            report[late_id]["joined_at_minute"] = join_minute

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    for agent_id in agents:
        r = report[agent_id]
        eff = f"{r['efficiency']:.2f}" if r["efficiency"] is not None else "n/a"
        print(f"{agent_id}: {r['packages_delivered']} delivered {r['delivered_packages']}, "
              f"distance {r['total_distance']:.2f}, efficiency {eff}"
              + (f", finished at minute {r['finish_time_minutes']:.2f}" if timed else ""))
    if late_id is not None:
        print(f"Late agent {late_id} joined at minute {join_minute:g} "
              f"and took {report[late_id]['packages_delivered']} package(s)")
    print(f"Best agent: {report['best_agent']}")
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
