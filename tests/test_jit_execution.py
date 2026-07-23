import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "jit_execution.py"
SPEC = importlib.util.spec_from_file_location("jit_execution", MODULE_PATH)
jit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(jit)


class JitPolicyTests(unittest.TestCase):
    def test_bounded_approval_off_policy(self):
        self.assertEqual(
            jit.exchange_approval_units(jit_policy=False, required_units=250_000),
            1_000_000,
        )

    def test_max_approval_only_under_policy(self):
        units = jit.exchange_approval_units(jit_policy=True, required_units=250_000)
        self.assertEqual(units, (1 << 256) - 1)
        self.assertEqual(units, jit.MAX_UINT256)

    def test_approval_rejects_nonpositive_requirement(self):
        with self.assertRaises(ValueError):
            jit.exchange_approval_units(jit_policy=True, required_units=0)

    def test_jit_funding_is_exact_without_margin(self):
        # Tight sizing is the balance-layer safety: no over-funding.
        self.assertEqual(jit.jit_fund_units(1_000_000), 1_000_000)

    def test_jit_funding_adds_fee_and_slippage_rounding_up(self):
        # 1.000000 pUSD, 2% fee + 1% slippage = 3% margin -> 1.030000 pUSD.
        self.assertEqual(
            jit.jit_fund_units(1_000_000, fee_bps=200, slippage_bps=100),
            1_030_000,
        )
        # Fractional base units always round up so the order is never underfunded.
        self.assertEqual(jit.jit_fund_units(333, fee_bps=100), 337)

    def test_jit_enabled_requires_explicit_flag(self):
        self.assertTrue(jit.jit_enabled({jit.JIT_ENV_FLAG: "1"}))
        self.assertFalse(jit.jit_enabled({jit.JIT_ENV_FLAG: "0"}))
        self.assertFalse(jit.jit_enabled({}))

    def test_word_uint_encodes_maxuint256_and_rejects_overflow(self):
        self.assertEqual(jit._word_uint(jit.MAX_UINT256), "f" * 64)
        self.assertEqual(jit._word_uint(0), "0" * 64)
        with self.assertRaises(ValueError):
            jit._word_uint(jit.MAX_UINT256 + 1)
        with self.assertRaises(ValueError):
            jit._word_uint(-1)

    def test_calldata_builders(self):
        spender = "0x" + "12" * 20
        approve = jit.erc20_approve_data(spender, jit.MAX_UINT256)
        self.assertTrue(approve.startswith("0x095ea7b3"))
        self.assertEqual(approve[-64:], "f" * 64)
        self.assertIn("12" * 20, approve)

        transfer = jit.erc20_transfer_data(spender, 100_000)
        self.assertTrue(transfer.startswith("0xa9059cbb"))
        self.assertEqual(transfer[-64:], format(100_000, "x").rjust(64, "0"))


if __name__ == "__main__":
    unittest.main()
