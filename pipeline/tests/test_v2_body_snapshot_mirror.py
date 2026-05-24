from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

from v2_build import build_v2_payload, mirror_v2_body_snapshot  # noqa: E402


class TestV2BodySnapshotMirror(unittest.TestCase):
    def test_build_v2_payload_mirrors_quantite_and_qty(self) -> None:
        body = "302970 24 7 AMLODIPINE MEDIS 10 MG B/30 COMP"
        payload = build_v2_payload({}, body, "bc_avenir")
        row = payload["line_items"][0]
        self.assertEqual(row.get("quantite"), 24)
        self.assertEqual(row.get("qty"), 24)

    def test_mirror_v2_body_snapshot_is_idempotent(self) -> None:
        payload = {
            "line_items": [{"code": "302970", "quantite": 24, "raw_line": "302970 24 7 AMLODIPINE"}]
        }
        once = mirror_v2_body_snapshot(payload)
        twice = mirror_v2_body_snapshot(once)
        self.assertEqual(once["line_items"][0]["qty"], 24)
        self.assertEqual(twice["line_items"][0]["quantite"], 24)
        self.assertEqual(twice["line_items"][0]["qty"], 24)


if __name__ == "__main__":
    unittest.main()
