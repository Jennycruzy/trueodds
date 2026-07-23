import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "buyer_funding.py"
SPEC = importlib.util.spec_from_file_location("buyer_funding", MODULE_PATH)
bf = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(bf)


class BuyerFundingPlanTests(unittest.TestCase):
    def test_already_funded_is_noop(self):
        self.assertEqual(bf.plan_pusd_funding({"pusd": 1_000_000}, 1_000_000), [])

    def test_margin_can_force_a_topup(self):
        # Exactly the notional but a 3% margin makes it short -> must wrap.
        plan = bf.plan_pusd_funding({"pusd": 1_000_000, "usdce": 500_000}, 1_000_000, margin_bps=300)
        self.assertEqual(plan, [{"action": "wrap", "from_token": "usdce", "to_token": "pusd", "amount_units": 30_000}])

    def test_usdce_wraps_the_exact_shortfall(self):
        plan = bf.plan_pusd_funding({"usdce": 2_000_000}, 1_500_000)
        self.assertEqual(plan, [{"action": "wrap", "from_token": "usdce", "to_token": "pusd", "amount_units": 1_500_000}])

    def test_partial_pusd_only_covers_shortfall(self):
        plan = bf.plan_pusd_funding({"pusd": 400_000, "usdce": 2_000_000}, 1_000_000)
        self.assertEqual(plan[0]["amount_units"], 600_000)

    def test_xlayer_route_grosses_up_and_floors_at_bridge_min(self):
        # Small order: bridge input is floored at the 2.5-token minimum.
        plan = bf.plan_pusd_funding({"xlayer_usdt0": 5_000_000}, 100_000)
        self.assertEqual(plan[0]["action"], "bridge")
        self.assertEqual(plan[0]["amount_units"], bf.BRIDGE_MIN_UNITS)
        self.assertEqual(plan[1], {"action": "wrap", "from_token": "usdce", "to_token": "pusd", "amount_units": bf.CREDITED})

    def test_xlayer_route_grosses_up_above_the_floor(self):
        # Large order: 5% fee gross-up dominates the floor.
        plan = bf.plan_pusd_funding({"xlayer_usdt0": 100_000_000}, 10_000_000, bridge_fee_bps=500)
        self.assertEqual(plan[0]["amount_units"], 10_500_000)

    def test_polygon_usdt_swaps_then_wraps(self):
        plan = bf.plan_pusd_funding({"polygon_usdt": 3_000_000}, 1_000_000)
        self.assertEqual([s["action"] for s in plan], ["swap", "wrap"])
        self.assertEqual(plan[0]["from_token"], "polygon_usdt")

    def test_insufficient_raises(self):
        with self.assertRaises(bf.FundingError):
            bf.plan_pusd_funding({"usdce": 100, "xlayer_usdt0": 100}, 1_000_000)

    def test_nonpositive_requirement_rejected(self):
        with self.assertRaises(ValueError):
            bf.plan_pusd_funding({"pusd": 1}, 0)


if __name__ == "__main__":
    unittest.main()
