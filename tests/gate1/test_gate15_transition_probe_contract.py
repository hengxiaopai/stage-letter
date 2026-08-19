from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "scripts" / "gate15_transition_persistence_probe.py"


class Gate15TransitionProbeContractTests(unittest.TestCase):
    def test_selected_session_columns_have_explicit_result_labels(self) -> None:
        source = PROBE.read_text(encoding="utf-8")

        for expression in (
            'LiveSessionModel.id.label("session_id")',
            'LiveSessionModel.opened_at.label("opened_at")',
            'LiveSessionModel.closed_at.label("closed_at")',
            'LiveSessionModel.origin.label("origin")',
            'LiveSessionModel.source_started_at.label("source_started_at")',
        ):
            self.assertIn(expression, source)

        self.assertIn("row.session_id", source)
        self.assertIn("row.opened_at", source)
        self.assertIn("row.closed_at", source)
        self.assertNotIn("LiveSessionModel.started_at", source)
        self.assertNotIn("LiveSessionModel.ended_at", source)


if __name__ == "__main__":
    unittest.main()
