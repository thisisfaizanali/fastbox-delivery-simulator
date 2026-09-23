"""FastBox delivery simulator.

Loads warehouses, agents and packages from JSON, assigns each package to the
nearest agent, and computes how far each agent travels.
"""

import json
import math
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
