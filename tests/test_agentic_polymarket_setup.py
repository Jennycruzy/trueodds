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

    def test_legacy_setup_does_not_encode_max_uint_approval(self):
        source = (Path(__file__).parents[1] / "scripts" / "g0_spike.py").read_text()
        self.assertNotIn("_word(MAX_UINT256)", source)

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
