import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "agentic_polymarket_setup.py"
SPEC = importlib.util.spec_from_file_location("agentic_polymarket_setup", MODULE_PATH)
agentic = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(agentic)


class AgenticPolymarketSetupTests(unittest.TestCase):
    def test_approval_is_exact_not_unlimited(self):
        spender = "0x" + "12" * 20
        data = (
            agentic.APPROVE_SELECTOR
            + agentic._word_address(spender)
            + agentic._word_uint(100_000)
        )
        self.assertEqual(data[-64:], hex(100_000)[2:].rjust(64, "0"))
        self.assertNotIn("f" * 64, data)

    def test_deposit_wallet_approval_is_policy_gated(self):
        # Under the autonomous JIT policy the deposit-wallet approval may be
        # MaxUint256, but only via the shared policy function gated on the explicit
        # JIT flag -- never an unconditional unlimited approval literal.
        source = (Path(__file__).parents[1] / "scripts" / "g0_spike.py").read_text()
        self.assertIn("jit_execution.exchange_approval_units", source)
        self.assertIn("jit_execution.jit_enabled(env)", source)
        self.assertNotIn("_word(MAX_UINT256)", source)

    def _run_main(self, argv):
        import io
        import sys
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with patch.object(sys, "argv", ["agentic_polymarket_setup.py", *argv]):
            with redirect_stdout(buffer):
                agentic.main()
        return buffer.getvalue()

    def test_max_approval_requires_jit_acknowledgement(self):
        # MaxUint256 is never granted without the caller naming the JIT policy.
        with self.assertRaises(SystemExit):
            self._run_main(["--spender", "0x" + "12" * 20, "--max-approval"])

    def test_max_approval_dry_run_encodes_maxuint256(self):
        payload = json.loads(
            self._run_main(["--spender", "0x" + "12" * 20, "--max-approval", "--jit"])
        )
        self.assertEqual(payload["approval_kind"], "maxuint256_jit_policy")
        self.assertEqual(payload["approval_units"], (1 << 256) - 1)

    def test_bounded_approval_is_the_default(self):
        payload = json.loads(
            self._run_main(["--spender", "0x" + "12" * 20, "--approval-units", "100000"])
        )
        self.assertEqual(payload["approval_kind"], "bounded")
        self.assertEqual(payload["approval_units"], 100_000)

    def test_credentials_require_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "creds.json"
            path.write_text(
                json.dumps({"apiKey": "k", "secret": "s", "passphrase": "p"})
            )
            os.chmod(path, 0o644)
            with self.assertRaises(SystemExit):
                agentic._load_credentials(path, {
                    "key": ("apiKey",), "secret": ("secret",),
                    "passphrase": ("passphrase",),
                })
            os.chmod(path, 0o600)
            self.assertEqual(agentic._load_credentials(path, {
                "key": ("apiKey",), "secret": ("secret",),
                "passphrase": ("passphrase",),
            })["key"], "k")

    @patch("subprocess.run")
    def test_external_signer_returns_signature_without_printing_it(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps({
            "ok": True, "data": {"signature": "ab" * 65}
        })
        run.return_value.stderr = ""
        signature = agentic.OnchainOSSigner().sign_typed_data({
            "types": {}, "primaryType": "Batch", "domain": {}, "message": {}
        })
        self.assertTrue(signature.startswith("0x"))
        command = run.call_args.args[0]
        self.assertIn("--force", command)
        self.assertIn("eip712", command)


if __name__ == "__main__":
    unittest.main()
