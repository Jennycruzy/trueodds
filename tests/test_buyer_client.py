import importlib.util
import unittest
from pathlib import Path


def _load(name):
    path = Path(__file__).parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


bc = _load("buyer_client")

USDCE = bc.USDCE.lower()
PUSD = bc.PUSD.lower()
ONRAMP = bc.COLLATERAL_ONRAMP.lower()
POLYGON_USDT = bc.buyer_funding.SOURCE_TOKENS["polygon_usdt"]["address"].lower()


class FakeSigner(bc.Signer):
    def __init__(self, address="0x" + "11" * 20):
        self._address = address
        self.sent = []

    def address(self):
        return self._address

    def sign_order(self, order_eip712):
        return "0x" + "cd" * 65

    def sign_and_send(self, tx):
        self.sent.append(tx)
        return "0x" + f"{len(self.sent):064x}"


class FakeRpc:
    """Scripts eth_call reads; every broadcast confirms with status 0x1."""

    def __init__(self, balances=None, allowances=None):
        self.balances = {k.lower(): v for k, v in (balances or {}).items()}
        self.allowances = {k.lower(): v for k, v in (allowances or {}).items()}

    def __call__(self, method, params):
        if method == "eth_call":
            to = params[0]["to"].lower()
            selector = params[0]["data"][:10]
            if selector == bc.SEL_BALANCE_OF:
                return hex(self.balances.get(to, 0))
            if selector == bc.SEL_ALLOWANCE:
                return hex(self.allowances.get(to, 0))
        if method == "eth_getTransactionReceipt":
            return {"status": "0x1"}
        raise AssertionError(f"unexpected rpc call: {method}")


class EnsurePusdTests(unittest.TestCase):
    def test_already_funded_does_nothing(self):
        rpc = FakeRpc(balances={PUSD: 1_000_000})
        signer = FakeSigner()
        result = bc.ensure_pusd(signer, rpc, 1_000_000)
        self.assertEqual(result["status"], "already_funded")
        self.assertEqual(signer.sent, [])

    def test_usdce_route_approves_then_wraps(self):
        rpc = FakeRpc(balances={USDCE: 2_000_000, PUSD: 0}, allowances={USDCE: 0})
        signer = FakeSigner()
        bc.ensure_pusd(signer, rpc, 1_000_000)
        self.assertEqual(len(signer.sent), 2)
        self.assertEqual(signer.sent[0]["to"].lower(), USDCE)     # approve on-ramp
        self.assertTrue(signer.sent[0]["data"].startswith(bc.SEL_APPROVE))
        self.assertEqual(signer.sent[1]["to"].lower(), ONRAMP)    # wrap
        self.assertTrue(signer.sent[1]["data"].startswith(bc.SEL_WRAP))

    def test_sufficient_allowance_skips_approve(self):
        rpc = FakeRpc(balances={USDCE: 2_000_000, PUSD: 0}, allowances={USDCE: 5_000_000})
        signer = FakeSigner()
        bc.ensure_pusd(signer, rpc, 1_000_000)
        self.assertEqual(len(signer.sent), 1)
        self.assertEqual(signer.sent[0]["to"].lower(), ONRAMP)

    def test_wrap_amount_is_the_shortfall(self):
        rpc = FakeRpc(balances={USDCE: 5_000_000, PUSD: 400_000}, allowances={USDCE: _big()})
        signer = FakeSigner()
        bc.ensure_pusd(signer, rpc, 1_000_000)
        wrapped = int(signer.sent[0]["data"][-64:], 16)
        self.assertEqual(wrapped, 600_000)

    def test_missing_injected_handler_is_a_clear_error(self):
        # Polygon USDT needs a swap handler, which is not built in.
        rpc = FakeRpc(balances={POLYGON_USDT: 3_000_000, PUSD: 0})
        signer = FakeSigner()
        with self.assertRaises(bc.ExecutionError):
            bc.ensure_pusd(signer, rpc, 1_000_000)

    def test_injected_swap_handler_runs_then_wrap(self):
        # USDC.e below the shortfall forces the planner onto the swap route; the
        # CREDITED wrap then consumes whatever USDC.e is present.
        rpc = FakeRpc(balances={POLYGON_USDT: 3_000_000, PUSD: 0, USDCE: 200_000}, allowances={USDCE: _big()})
        signer = FakeSigner()
        calls = []

        def swap(signer_, rpc_, step):
            calls.append(step["action"])
            return "0xswap"

        result = bc.ensure_pusd(signer, rpc, 1_000_000, handlers={"swap": swap})
        self.assertEqual(calls, ["swap"])
        self.assertEqual([s["action"] for s in result["steps"]], ["swap", "wrap"])


def _big():
    return (1 << 256) - 1


if __name__ == "__main__":
    unittest.main()
