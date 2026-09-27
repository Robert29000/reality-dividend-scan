from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reality_dividends.config import ALCHEMY_PROVIDER
from reality_dividends.state import ScanState, StateError


class StateTests(unittest.TestCase):
    def test_rejects_reversed_requested_range(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(StateError, "end block"):
                ScanState(
                    Path(directory) / "state.json",
                    ALCHEMY_PROVIDER,
                    2,
                    1,
                )

    def test_save_only_writes_when_state_changes(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "reality_dividends.state.atomic_json"
        ) as atomic_json:
            state = ScanState(
                Path(directory) / "state.json",
                ALCHEMY_PROVIDER,
                1,
                10,
            )
            state.save()
            state.save()
            self.assertEqual(atomic_json.call_count, 1)

            state.complete(1, 10)
            state.save()
            state.save()
            self.assertEqual(atomic_json.call_count, 2)

    def test_existing_state_extends_requested_end(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            ScanState(path, ALCHEMY_PROVIDER, 1, 10).save()

            state = ScanState(path, ALCHEMY_PROVIDER, 1, 20)
            self.assertEqual(state.requested_to, 20)
            state.save()

            reloaded = ScanState(path, ALCHEMY_PROVIDER, 1, 20)
            self.assertEqual(reloaded.requested_to, 20)


if __name__ == "__main__":
    unittest.main()
