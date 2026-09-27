from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reality_dividends import cli


class FakeCollector:
    instances = []

    def __init__(self, provider, rpc_url, state):
        self.provider = provider
        self.rpc_url = rpc_url
        self.state = state
        self.__class__.instances.append(self)

    def validate_chain(self):
        pass

    def head_block(self):
        return 462_326_600

    def collect(self, start, end):
        self.state.complete(start, end)
        self.state.save()


class CliTests(unittest.TestCase):
    def setUp(self):
        FakeCollector.instances.clear()

    def run_case(self, mode, provider, output_type):
        with tempfile.TemporaryDirectory() as directory:
            args = [
                mode,
                "--provider",
                provider,
                "--output-dir",
                directory,
                "--output-type",
                output_type,
            ]
            if mode == "range":
                args += [
                    "--from-block",
                    str(cli.CREATION_BLOCK),
                    "--to-block",
                    str(cli.CREATION_BLOCK + 9),
                ]
            environment = {
                "ALCHEMY_RPC_URL": "https://example.invalid/alchemy-secret",
                "DRPC_RPC_URL": "https://example.invalid/drpc-secret",
            }
            with patch.dict(os.environ, environment, clear=True), patch.object(
                cli, "RpcCollector", FakeCollector
            ):
                self.assertEqual(cli.main(args), 0)

            output = Path(directory)
            expected_suffix = ".csv" if output_type == "csv" else ".md"
            other_suffix = ".md" if output_type == "csv" else ".csv"
            self.assertTrue(
                (output / f"dividends-{provider}{expected_suffix}").exists()
            )
            self.assertFalse(
                (output / f"dividends-{provider}{other_suffix}").exists()
            )
            states = list(output.glob(".*-state.json"))
            self.assertEqual(len(states), 1)
            self.assertNotIn("secret", states[0].read_text())
            self.assertEqual(FakeCollector.instances[-1].provider, provider)

    def test_all_mode_provider_combinations(self):
        for mode in ("creation", "range"):
            for provider in ("alchemy", "drpc"):
                for output_type in ("csv", "markdown"):
                    with self.subTest(
                        mode=mode, provider=provider, output_type=output_type
                    ):
                        self.run_case(mode, provider, output_type)

    def test_rejects_range_before_creation_block(self):
        with patch.dict(os.environ, {"ALCHEMY_RPC_URL": "secret"}, clear=True):
            self.assertEqual(
                cli.main(
                    [
                        "range",
                        "--provider",
                        "alchemy",
                        "--output-type",
                        "csv",
                        "--from-block",
                        str(cli.CREATION_BLOCK - 1),
                        "--to-block",
                        str(cli.CREATION_BLOCK),
                    ]
                ),
                2,
            )

    def test_rejects_reversed_range(self):
        with patch.dict(os.environ, {"ALCHEMY_RPC_URL": "secret"}, clear=True):
            self.assertEqual(
                cli.main(
                    [
                        "range",
                        "--provider",
                        "alchemy",
                        "--output-type",
                        "csv",
                        "--from-block",
                        str(cli.CREATION_BLOCK + 1),
                        "--to-block",
                        str(cli.CREATION_BLOCK),
                    ]
                ),
                2,
            )

    def test_requires_selected_provider_url(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                cli.main(
                    [
                        "range",
                        "--provider",
                        "drpc",
                        "--output-type",
                        "csv",
                        "--from-block",
                        str(cli.CREATION_BLOCK),
                        "--to-block",
                        str(cli.CREATION_BLOCK + 1),
                    ]
                ),
                2,
            )

    def test_removed_options_are_not_accepted(self):
        parser = cli.build_parser()
        for option in ("--dry-run", "--state", "--manifest"):
            with self.subTest(option=option), self.assertRaises(SystemExit):
                parser.parse_args(
                    [
                        "range",
                        "--provider",
                        "alchemy",
                        "--output-type",
                        "csv",
                        "--from-block",
                        str(cli.CREATION_BLOCK),
                        "--to-block",
                        str(cli.CREATION_BLOCK + 1),
                        option,
                        *([] if option == "--dry-run" else ["value"]),
                    ]
                )


if __name__ == "__main__":
    unittest.main()
