# FastBox Delivery Simulator

Simulates one day of FastBox deliveries. It reads warehouses, agents and
packages from a JSON file, assigns each package to an agent, routes every
agent through its deliveries, and writes a per-agent report to `report.json`.

**Requirements:** Python 3.12 (3.8+ is likely fine, but only 3.12 was
tested). Standard library only; there is nothing to install.

## Assignment coverage

| Task | Where |
|---|---|
| 1. Read and parse the JSON file | `load_data` (both input layouts, with validation) |
| 2. Assign each package to the nearest agent | `assign_packages`, Euclidean `distance` |
| 3. Simulate pickup and delivery, total distance | `simulate` |
| 4. Generate the report | `build_report` |
| 5. Save to `report.json` | `main` (`-o` to choose another path) |
| Bonus: random delivery delays | `--delays [--seed N]` |
| Bonus: visualize routes in ASCII | `--ascii` (`render_ascii`) |
| Bonus: new agent joining mid-day | `--late-agent ID X Y MINUTE` (`add_late_agent`) |
| Bonus: export top performer to CSV | `--csv [PATH]` (`export_top_performer`) |
| Delivered count matches total packages | checked at runtime in `build_report` and in the tests for every input file |

## Usage

```
python delivery.py                                   # reads data.json, writes report.json
python delivery.py test_cases/test_case_3.json -o out.json
```

```
$ python delivery.py
A1: 2 delivered ['P4', 'P1'], distance 57.27, efficiency 28.63
A2: 2 delivered ['P5', 'P2'], distance 60.83, efficiency 30.42
A3: 1 delivered ['P3'], distance 14.14, efficiency 14.14
Best agent: A3
Report written to report.json
```

Invalid input prints `Error: ...` to stderr and exits with code 1.

### Optional flags

All flags are opt-in. Without them the output is exactly as above.

`--delays [--seed N]` adds a random 0-10 minute delay to each drop-off
(default seed 42) and reports finish times:

```
$ python delivery.py --delays --seed 7
A1: 2 delivered ['P4', 'P1'], distance 57.27, efficiency 28.63, finished at minute 62.55
A2: 2 delivered ['P5', 'P2'], distance 60.83, efficiency 30.42, finished at minute 71.05
A3: 1 delivered ['P3'], distance 14.14, efficiency 14.14, finished at minute 20.25
Best agent: A3
Report written to report.json
```

`--late-agent ID X Y MINUTE` adds an agent who starts at (X, Y) at the given
minute and takes over batches it can reach first:

```
$ python delivery.py --late-agent A9 45 70 0
A1: 2 delivered ['P4', 'P1'], distance 57.27, efficiency 28.63, finished at minute 57.27
A2: 0 delivered [], distance 0.00, efficiency n/a, finished at minute 0.00
A3: 1 delivered ['P3'], distance 14.14, efficiency 14.14, finished at minute 14.14
A9: 2 delivered ['P5', 'P2'], distance 49.87, efficiency 24.94, finished at minute 49.87
Late agent A9 joined at minute 0 and took 2 package(s)
Best agent: A3
Report written to report.json
```

`--ascii` prints a map of the routes after the summary. Each agent's route is
drawn with its number from the legend:

```
$ python delivery.py --ascii
...
+------------------------------------------------------------+
|                                   2222*                    |
|                           22222222                         |
|                      *2222                                 |
|                          22W                               |
|                             222                            |
|                                2                           |
|                                 2@                         |
|                                                            |
|                                                            |
|                                                            |
|                                                            |
|                 *                                          |
|               11                                           |
|             11                                      @3     |
|           11                                          3W3  |
|         11                                               3*|
|       11                                                   |
|     1*                                                     |
|  1@1                                                       |
|W1                                                          |
+------------------------------------------------------------+
1 = A1
2 = A2
3 = A3
@ agent start  W warehouse  * destination
```

`--csv [PATH]` writes the best agent's row to a CSV file (default
`top_performer.csv`):

```
$ python delivery.py --csv
...
Top performer written to top_performer.csv
$ cat top_performer.csv
agent_id,packages_delivered,total_distance,efficiency,delivered_packages
A3,1,14.14,14.14,P3
```

### Tests

```
$ python -m unittest -v
...
Ran 22 tests in 0.364s

OK
```

## Input formats

Two layouts are accepted and parse to the same data.

Dict form (`data.json`, `test_cases/test_case_*.json`):

```json
{
  "warehouses": {"W1": [0, 0]},
  "agents": {"A1": [5, 5]},
  "packages": [{"id": "P1", "warehouse": "W1", "destination": [30, 40]}]
}
```

List form (`test_cases/base_case.json`):

```json
{
  "warehouses": [{"id": "W1", "location": [0, 0]}],
  "agents": [{"id": "A1", "location": [5, 5]}],
  "packages": [{"id": "P1", "warehouse_id": "W1", "destination": [30, 40]}]
}
```

## Report format

`report.json` for `data.json`:

```json
{
  "A1": {
    "packages_delivered": 2,
    "total_distance": 57.27,
    "efficiency": 28.63,
    "delivered_packages": [
      "P4",
      "P1"
    ]
  },
  "A2": {
    "packages_delivered": 2,
    "total_distance": 60.83,
    "efficiency": 30.42,
    "delivered_packages": [
      "P5",
      "P2"
    ]
  },
  "A3": {
    "packages_delivered": 1,
    "total_distance": 14.14,
    "efficiency": 14.14,
    "delivered_packages": [
      "P3"
    ]
  },
  "best_agent": "A3"
}
```

- `packages_delivered`: number of packages the agent delivered.
- `total_distance`: distance travelled, rounded to 2 decimals.
- `efficiency`: total distance / packages delivered. **Lower is better.**
  `null` for an agent with no deliveries.
- `delivered_packages`: package ids in delivery order.
- `best_agent`: the agent with the lowest efficiency (`null` if nothing was
  delivered).

Fields added only when a flag is used:

- `finish_time_minutes`: minute the agent finished (with `--delays` or `--late-agent`).
- `total_delay_minutes`: sum of the agent's random delays (with `--delays`).
- `joined_at_minute`: when the late agent joined (on the late agent only).

## How it works

1. **Assignment.** Each package goes to the agent whose start point is
   closest to the package's warehouse, using Euclidean distance
   `sqrt((x2 - x1)^2 + (y2 - y1)^2)`.
2. **Route (batched, nearest first).** From its start, an agent goes to the
   nearest warehouse that still holds any of its packages, picks up all of
   them, and delivers them nearest destination first. It repeats this until
   everything is delivered. There is no return trip.
3. **Time.** Agents move 1 distance unit per minute and the day starts at
   minute 0. With `--delays`, each drop-off adds a random 0-10 minutes.
4. **Late agent.** A batch whose agent has not left for the warehouse by the
   join minute moves to the late agent if the late agent would reach that
   warehouse strictly earlier than the assigned agent's planned arrival.
   The day is then simulated again.

### Worked example (`data.json`)

Distances from each agent's start to W1 (0, 0) are A1 7.07, A2 84.85 and
A3 99.62, so A1 gets both W1 packages (P1, P4). In the same way A2 gets the
W2 packages and A3 gets the W3 package.

| Agent | Route | Legs | Total | Efficiency |
|---|---|---|---|---|
| A1 | (5,5) → W1 (0,0) → P4 (10,10) → P1 (30,40) | 7.07 + 14.14 + 36.06 | 57.27 | 57.27 / 2 = 28.63 |
| A2 | (60,60) → W2 (50,75) → P5 (40,80) → P2 (70,90) | 18.03 + 11.18 + 31.62 | 60.83 | 60.83 / 2 = 30.42 |
| A3 | (95,30) → W3 (100,25) → P3 (105,20) | 7.07 + 7.07 | 14.14 | 14.14 / 1 = 14.14 |

A3 has the lowest distance per package, so it is `best_agent`.

## Assumptions and design decisions

- "Parse the JSON file manually" is read as opening and parsing the file
  ourselves with `open()` and the stdlib `json` module, not writing a JSON
  parser by hand.
- Assignment uses the distance from the agent's start to the warehouse, as
  the spec says. There is no load balancing (the spec doesn't ask for it),
  so one agent may get many packages and another none.
- Pickups are batched and capacity is unlimited. An agent ends at its last
  drop-off and does not return to base.
- Tie-breaks: equally near agents go to the first agent in input order;
  warehouse and destination ties go by input order; a `best_agent` tie goes
  to the agent with more deliveries, then input order.
- Agents with no packages are still reported, with distance 0 and
  efficiency `null`, and are never `best_agent`.
- Values are rounded to 2 decimals only in the output. All calculations use
  full precision.
- Invalid input fails with an error message and exit code 1 instead of
  skipping data. That covers unknown warehouses, malformed or non-finite
  coordinates, ids that are not non-empty strings, duplicate ids or keys, an
  agent named `best_agent` (it would clash with the report key), and missing
  sections. As a result the
  number delivered always equals the number of packages, and this is also
  checked at runtime.
- The sample report in the assignment PDF is illustrative. Its package counts
  match this assignment, but its distances can't be reproduced from the given
  data under any consistent route model, so these values are computed, not
  matched to it.
- `delivered_packages` is an extra field that lists which packages each agent
  delivered, since the scenario asks the report to show this. The required
  fields are unchanged.
- Time model: 1 distance unit per minute, starting at minute 0. Delays are
  uniform 0-10 minutes per drop-off, derived from seed + agent + package, so
  runs are reproducible. Delays change time, never distance.
- Late agent: waiting batches move by earliest arrival (see above). Arrival
  estimates come from the original plan. Removing a batch can make the
  original agent's later batches arrive earlier than estimated, and this is
  not recalculated.
- Agent ids sit at the top level of the report next to `best_agent`, to
  match the sample format in the spec.

## Project structure

```
delivery.py        simulator: parsing, assignment, routing, report, CLI
test_delivery.py   unit tests (unittest)
data.json          sample input from the assignment
report.json        report generated from data.json (python delivery.py)
test_cases/        provided inputs: base_case.json (list form), test_case_1-10.json
README.md          this file
```
