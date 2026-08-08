"""Tests for the documentation and record system itself.

Documentation rots silently; these tests make it fail loudly instead. They
check that data records match their schemas, that every journal entry has a
machine-readable twin, and that internal links actually resolve.

Schema checking is a deliberately small subset of JSON Schema -- required keys,
types, enums and patterns -- implemented here rather than pulled in, because
the zero-dependency rule applies to tests too.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "data" / "schema"
SESSIONS_DIR = ROOT / "data" / "sessions"
BASELINES_DIR = ROOT / "data" / "baselines"
JOURNAL_DIR = ROOT / "journal"

TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def type_matches(value, spec) -> bool:
    names = spec if isinstance(spec, list) else [spec]
    # bool is a subclass of int in Python; an integer field must not accept True.
    if isinstance(value, bool) and "boolean" not in names:
        return False
    return any(isinstance(value, TYPES[name]) for name in names if name in TYPES)


def validate(instance, schema, path: str, errors: list[str]) -> None:
    """Check the subset of JSON Schema this project actually uses."""
    if "type" in schema and not type_matches(instance, schema["type"]):
        errors.append(f"{path}: expected {schema['type']}, got {type(instance).__name__}")
        return

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in {schema['enum']}")

    if "pattern" in schema and isinstance(instance, str):
        if not re.match(schema["pattern"], instance):
            errors.append(f"{path}: {instance!r} does not match {schema['pattern']}")

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required field {key!r}")
        properties = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in properties:
                validate(value, properties[key], f"{path}.{key}", errors)
            elif extra is False:
                errors.append(f"{path}: unexpected field {key!r}")
            elif isinstance(extra, dict):
                validate(value, extra, f"{path}.{key}", errors)

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: needs at least {schema['minItems']} items")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(instance):
                validate(item, item_schema, f"{path}[{index}]", errors)


class TestSessionRecords(unittest.TestCase):
    def setUp(self):
        self.schema = load(SCHEMA_DIR / "session-review.schema.json")
        self.records = sorted(SESSIONS_DIR.glob("*.json"))

    def test_at_least_one_session_exists(self):
        self.assertTrue(self.records)

    def test_every_record_matches_the_schema(self):
        for path in self.records:
            with self.subTest(record=path.name):
                errors: list[str] = []
                validate(load(path), self.schema, path.stem, errors)
                self.assertEqual(errors, [], "\n".join(errors))

    def test_filenames_encode_date_and_id(self):
        for path in self.records:
            with self.subTest(record=path.name):
                match = re.match(r"^(\d{4}-\d{2}-\d{2})-(S\d{3})$", path.stem)
                self.assertIsNotNone(match, f"{path.name} is misnamed")
                record = load(path)
                self.assertEqual(record["date"], match.group(1))
                self.assertEqual(record["id"], match.group(2))

    def test_session_ids_are_unique_and_contiguous(self):
        ids = sorted(int(load(p)["id"][1:]) for p in self.records)
        self.assertEqual(ids, list(range(1, len(ids) + 1)))

    def test_every_record_has_a_journal_entry(self):
        """The prose and the data are written together or not at all."""
        for path in self.records:
            with self.subTest(record=path.name):
                journal = ROOT / load(path)["journal"]
                self.assertTrue(journal.exists(), f"missing journal: {journal}")

    def test_every_journal_entry_has_a_data_record(self):
        entries = [p for p in JOURNAL_DIR.glob("*.md")
                   if p.name not in {"README.md", "TEMPLATE.md"}]
        self.assertTrue(entries)
        referenced = {(ROOT / load(p)["journal"]).resolve() for p in self.records}
        for entry in entries:
            with self.subTest(entry=entry.name):
                self.assertIn(entry.resolve(), referenced)

    def test_trajectories_referenced_by_records_exist(self):
        for path in self.records:
            record = load(path)
            owners = {record["trajectory"]}
            owners.update(q["owner"] for q in record["open_questions"])
            for owner in owners:
                with self.subTest(record=path.name, trajectory=owner):
                    matches = list((ROOT / "docs" / "trajectories").glob(f"{owner}-*.md"))
                    self.assertTrue(matches, f"no document for {owner}")

    def test_unverified_claims_are_marked_not_omitted(self):
        """A claim with no evidence must say so rather than be left out."""
        for path in self.records:
            record = load(path)
            with self.subTest(record=path.name):
                self.assertTrue(record["evidence"], "evidence may not be empty")
                for item in record["evidence"]:
                    if item["verdict"] == "verified":
                        self.assertTrue(
                            item["method"],
                            f"{path.name}: a verified claim needs a method",
                        )

    def test_metrics_are_self_consistent(self):
        for path in self.records:
            metrics = load(path)["metrics"]
            with self.subTest(record=path.name):
                self.assertLessEqual(
                    metrics["tests_passing"], metrics["tests_total"]
                )


class TestBaselines(unittest.TestCase):
    def setUp(self):
        self.schema = load(SCHEMA_DIR / "baseline.schema.json")
        self.records = sorted(BASELINES_DIR.glob("*.json"))

    def test_every_baseline_matches_the_schema(self):
        self.assertTrue(self.records)
        for path in self.records:
            with self.subTest(baseline=path.name):
                errors: list[str] = []
                validate(load(path), self.schema, path.stem, errors)
                self.assertEqual(errors, [], "\n".join(errors))

    def test_baselines_cover_every_current_level(self):
        """A level added without refreshing the baseline is a silent gap."""
        from vibecoder.levels import all_levels

        latest = load(self.records[-1])
        for level in all_levels():
            with self.subTest(level=level.id):
                self.assertIn(level.id, latest["levels"])

    def test_recorded_op_counts_still_reproduce(self):
        """Guards the instrumentation and the level generators at once.

        If this fails, either a reference solution changed, a level's generated
        data changed, or op counting changed. All three are worth knowing about.
        """
        from vibecoder.levels import get_level
        from vibecoder.runner import reference_benchmark

        latest = load(self.records[-1])
        for level_id, entry in latest["levels"].items():
            level = get_level(level_id)
            for seed, expected in entry["reference_ops_by_seed"].items():
                with self.subTest(level=level_id, seed=seed):
                    ops, _ = reference_benchmark(level, int(seed))
                    self.assertEqual(
                        ops,
                        expected["ops"],
                        f"{level_id} seed {seed}: {ops} ops, baseline says "
                        f"{expected['ops']}",
                    )


class TestInternalLinks(unittest.TestCase):
    """Relative Markdown links must resolve. Broken links are how docs rot."""

    LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

    # Templates link to placeholder paths on purpose (YYYY-MM-DD-Snnn.json).
    SKIP = {"TEMPLATE.md"}

    def markdown_files(self) -> list[Path]:
        return [
            path
            for path in ROOT.rglob("*.md")
            if path.name not in self.SKIP
            and not any(part.startswith(".") for part in path.relative_to(ROOT).parts)
        ]

    def test_all_relative_links_resolve(self):
        broken: list[str] = []
        for path in self.markdown_files():
            for target in self.LINK.findall(path.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                resolved = (path.parent / target.split("#", 1)[0]).resolve()
                if not resolved.exists():
                    broken.append(f"{path.relative_to(ROOT)} -> {target}")
        self.assertEqual(broken, [], "broken links:\n" + "\n".join(broken))

    def test_every_trajectory_is_on_the_flight_board(self):
        board = (ROOT / "docs" / "trajectories" / "README.md").read_text(
            encoding="utf-8"
        )
        for path in (ROOT / "docs" / "trajectories").glob("T*.md"):
            with self.subTest(trajectory=path.name):
                self.assertIn(path.name, board)

    def test_every_trajectory_declares_a_status(self):
        allowed = {"LANDED", "IN FLIGHT", "CLEARED", "PLOTTED", "HOLDING"}
        for path in (ROOT / "docs" / "trajectories").glob("T*.md"):
            with self.subTest(trajectory=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertTrue(
                    any(f"`{status}`" in text for status in allowed),
                    f"{path.name} declares no status",
                )


if __name__ == "__main__":
    unittest.main()
