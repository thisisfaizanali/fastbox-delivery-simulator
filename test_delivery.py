"""Unit tests for delivery.py. Run with: python -m unittest -v"""

import csv
import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest

import delivery

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data.json")


def run_pipeline(path):
    """Load, assign, simulate and report for one input file."""
    warehouses, agents, packages = delivery.load_data(path)
    assignments = delivery.assign_packages(warehouses, agents, packages)
    results = delivery.simulate(warehouses, agents, assignments)
    return packages, delivery.build_report(results, len(packages))


class DistanceTests(unittest.TestCase):
    def test_distance_3_4_5(self):
        """A 3-4-5 right triangle has hypotenuse 5."""
        self.assertEqual(delivery.distance((0, 0), (3, 4)), 5)

    def test_distance_symmetric(self):
        """distance(a, b) equals distance(b, a)."""
        a, b = (1.5, -2), (7, 11)
        self.assertEqual(delivery.distance(a, b), delivery.distance(b, a))


class LoadTests(unittest.TestCase):
    def test_both_formats_match(self):
        """Dict-form data.json and list-form base_case.json parse to the same data."""
        self.assertEqual(
            delivery.load_data(DATA),
            delivery.load_data(os.path.join(HERE, "test_cases", "base_case.json")),
        )

    def test_invalid_inputs_raise(self):
        """Each kind of malformed input raises ValueError."""
        good_w = '"warehouses": {"W1": [0, 0]}'
        good_a = '"agents": {"A1": [1, 1]}'
        pkg = '{"id": "P1", "warehouse": "W1", "destination": %s}'
        cases = {
            "unknown warehouse": '{%s, %s, "packages": [{"id": "P1", "warehouse": "W9", "destination": [1, 2]}]}' % (good_w, good_a),
            "coord [1]": '{%s, %s, "packages": [%s]}' % (good_w, good_a, pkg % "[1]"),
            'coord "a"': '{%s, %s, "packages": [%s]}' % (good_w, good_a, pkg % '"a"'),
            "coord [true, 1]": '{%s, %s, "packages": [%s]}' % (good_w, good_a, pkg % "[true, 1]"),
            "NaN coord": '{%s, %s, "packages": [%s]}' % (good_w, good_a, pkg % "[NaN, 1]"),
            "duplicate package": '{%s, %s, "packages": [%s, %s]}' % (good_w, good_a, pkg % "[1, 2]", pkg % "[3, 4]"),
            "duplicate agent key": '{%s, "agents": {"A1": [1, 1], "A1": [2, 2]}, "packages": []}' % good_w,
            "missing packages": "{%s, %s}" % (good_w, good_a),
            "numeric package id": '{%s, %s, "packages": [{"id": 1, "warehouse": "W1", "destination": [1, 2]}]}' % (good_w, good_a),
            "list warehouse ref": '{%s, %s, "packages": [{"id": "P1", "warehouse": ["W1"], "destination": [1, 2]}]}' % (good_w, good_a),
            "list-form list id": '{"warehouses": [{"id": ["W1"], "location": [0, 0]}], %s, "packages": []}' % good_a,
            "reserved agent id": '{%s, "agents": {"best_agent": [1, 1]}, "packages": []}' % good_w,
        }
        for name, text in cases.items():
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as tmp:
                    path = os.path.join(tmp, "input.json")
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(text)
                    with self.assertRaises(ValueError):
                        delivery.load_data(path)


class AssignTests(unittest.TestCase):
    def test_data_json_assignment(self):
        """data.json packages go to the nearest agent."""
        assignments = delivery.assign_packages(*delivery.load_data(DATA))
        ids = {a: [p["id"] for p in pkgs] for a, pkgs in assignments.items()}
        self.assertEqual(ids, {"A1": ["P1", "P4"], "A2": ["P2", "P5"], "A3": ["P3"]})

    def test_tie_goes_to_first_agent(self):
        """Two agents at equal distance: the first one in input order wins."""
        warehouses = {"W1": (0.0, 0.0)}
        agents = {"B": (3.0, 4.0), "A": (-3.0, -4.0)}
        packages = [{"id": "P1", "warehouse": "W1", "destination": (1.0, 1.0)}]
        assignments = delivery.assign_packages(warehouses, agents, packages)
        self.assertEqual([p["id"] for p in assignments["B"]], ["P1"])
        self.assertEqual(assignments["A"], [])


class SimulateAndReportTests(unittest.TestCase):
    def test_batched_route_order(self):
        """A1 picks up both W1 packages at once and delivers the nearer one first."""
        _, report = run_pipeline(DATA)
        self.assertEqual(report["A1"]["delivered_packages"], ["P4", "P1"])

    def test_data_json_report(self):
        """Report numbers for data.json match the hand-computed values."""
        _, report = run_pipeline(DATA)
        expected = {"A1": (57.27, 28.63), "A2": (60.83, 30.42), "A3": (14.14, 14.14)}
        for agent, (dist, eff) in expected.items():
            with self.subTest(agent):
                self.assertAlmostEqual(report[agent]["total_distance"], dist, places=2)
                self.assertAlmostEqual(report[agent]["efficiency"], eff, places=2)
        self.assertEqual(report["best_agent"], "A3")

    def test_idle_agent(self):
        """An agent with no packages has zero distance, no efficiency and is never best."""
        warehouses = {"W1": (0.0, 0.0)}
        agents = {"A1": (1.0, 0.0), "A2": (100.0, 100.0)}
        packages = [{"id": "P1", "warehouse": "W1", "destination": (5.0, 0.0)}]
        assignments = delivery.assign_packages(warehouses, agents, packages)
        report = delivery.build_report(
            delivery.simulate(warehouses, agents, assignments), len(packages)
        )
        self.assertEqual(report["A2"]["packages_delivered"], 0)
        self.assertEqual(report["A2"]["total_distance"], 0)
        self.assertIsNone(report["A2"]["efficiency"])
        self.assertEqual(report["best_agent"], "A1")

    def test_every_package_delivered_once(self):
        """For every input file, each package is delivered exactly once."""
        paths = [DATA] + sorted(glob.glob(os.path.join(HERE, "test_cases", "*.json")))
        for path in paths:
            with self.subTest(os.path.basename(path)):
                packages, report = run_pipeline(path)
                agents = [v for k, v in report.items() if k != "best_agent"]
                self.assertEqual(sum(a["packages_delivered"] for a in agents), len(packages))
                delivered = sorted(pid for a in agents for pid in a["delivered_packages"])
                self.assertEqual(delivered, sorted(p["id"] for p in packages))


class TimeTests(unittest.TestCase):
    def setUp(self):
        self.w, self.a, self.p = delivery.load_data(DATA)
        self.assign = delivery.assign_packages(self.w, self.a, self.p)

    def test_same_seed_same_result(self):
        """The same seed gives identical results."""
        first = delivery.simulate(self.w, self.a, self.assign, seed=7)
        self.assertEqual(first, delivery.simulate(self.w, self.a, self.assign, seed=7))

    def test_delays_change_time_not_distance(self):
        """Delays leave total_distance unchanged but make agents finish later."""
        plain = delivery.simulate(self.w, self.a, self.assign)
        delayed = delivery.simulate(self.w, self.a, self.assign, seed=7)
        for agent in self.a:
            with self.subTest(agent):
                self.assertEqual(plain[agent]["total_distance"], delayed[agent]["total_distance"])
                self.assertGreater(delayed[agent]["finish_time"], plain[agent]["finish_time"])

    def test_late_agent_report(self):
        """A late agent is listed last, every package is still delivered once."""
        results = delivery.simulate(self.w, self.a, self.assign)
        agents2, _, results2 = delivery.add_late_agent(
            self.w, self.a, self.p, self.assign, results, "A9", (50.0, 50.0), 30.0, None)
        report = delivery.build_report(results2, len(self.p))  # raises if the invariant breaks
        self.assertEqual(list(agents2)[-1], "A9")
        self.assertIn("A9", report)

    def test_late_agent_existing_id_rejected(self):
        """Reusing an existing agent id raises ValueError."""
        results = delivery.simulate(self.w, self.a, self.assign)
        with self.assertRaises(ValueError):
            delivery.add_late_agent(
                self.w, self.a, self.p, self.assign, results, "A1", (0.0, 0.0), 0.0, None)

    def test_late_agent_takes_nearby_warehouse(self):
        """A late agent standing on a far warehouse at minute 0 takes its packages."""
        warehouses = {"W1": (0.0, 0.0), "W2": (100.0, 0.0)}
        agents = {"A1": (0.0, 0.0)}
        packages = [
            {"id": "P1", "warehouse": "W1", "destination": (1.0, 0.0)},
            {"id": "P2", "warehouse": "W2", "destination": (101.0, 0.0)},
        ]
        assignments = delivery.assign_packages(warehouses, agents, packages)
        results = delivery.simulate(warehouses, agents, assignments)
        _, _, results2 = delivery.add_late_agent(
            warehouses, agents, packages, assignments, results, "L", (100.0, 0.0), 0.0, None)
        self.assertEqual(results2["L"]["delivered"], ["P2"])
        self.assertEqual(results2["A1"]["delivered"], ["P1"])

    def test_late_agent_arrives_first(self):
        """In test_case_10, A5 at (10, 15) from minute 20 takes P4 and P10 from A3."""
        w, a, p = delivery.load_data(os.path.join(HERE, "test_cases", "test_case_10.json"))
        assign = delivery.assign_packages(w, a, p)
        results = delivery.simulate(w, a, assign)
        _, assign2, results2 = delivery.add_late_agent(
            w, a, p, assign, results, "A5", (10.0, 15.0), 20.0, None)
        self.assertEqual(sorted(results2["A5"]["delivered"]), ["P10", "P4"])
        self.assertNotIn("P4", [x["id"] for x in assign2["A3"]])
        delivery.build_report(results2, len(p))  # raises if the invariant breaks

    def test_cli_late_agent_fields(self):
        """--late-agent adds joined_at_minute to the late agent's report entry."""
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "report.json")
            proc = subprocess.run(
                [sys.executable, "delivery.py", "data.json", "-o", out,
                 "--late-agent", "A9", "50", "50", "30"],
                cwd=HERE, capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["A9"]["joined_at_minute"], 30)


class OutputTests(unittest.TestCase):
    def test_ascii_map(self):
        """The ASCII map shows warehouses, agent starts, destinations and a legend."""
        w, a, p = delivery.load_data(DATA)
        results = delivery.simulate(w, a, delivery.assign_packages(w, a, p))
        text = delivery.render_ascii(w, a, p, results)
        for mark in ("W", "@", "*", "1 = A1"):
            self.assertIn(mark, text)

    def test_csv_best_agent(self):
        """The CSV holds the header and one row for best agent A3."""
        _, report = run_pipeline(DATA)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "top.csv")
            delivery.export_top_performer(report, path)
            with open(path, encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
        self.assertEqual(rows[0], ["agent_id", "packages_delivered", "total_distance",
                                   "efficiency", "delivered_packages"])
        self.assertEqual(rows[1:], [["A3", "1", "14.14", "14.14", "P3"]])

    def test_csv_no_deliveries(self):
        """With no deliveries the CSV has only the header."""
        report = delivery.build_report({"A1": {"delivered": [], "total_distance": 0.0}}, 0)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "top.csv")
            delivery.export_top_performer(report, path)
            with open(path, encoding="utf-8", newline="") as f:
                self.assertEqual(len(list(csv.reader(f))), 1)


class CliTests(unittest.TestCase):
    def test_cli_writes_report(self):
        """The CLI exits 0 and writes a report naming A3 as best agent."""
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "report.json")
            proc = subprocess.run(
                [sys.executable, "delivery.py", "data.json", "-o", out],
                cwd=HERE, capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["best_agent"], "A3")

    def test_cli_missing_file(self):
        """A missing input file gives exit code 1 and an Error message."""
        proc = subprocess.run(
            [sys.executable, "delivery.py", "no_such_file.json"],
            cwd=HERE, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Error:", proc.stderr)


if __name__ == "__main__":
    unittest.main()
