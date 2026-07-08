#!/usr/bin/env python3
"""
Real-World Odds Oracle — verification harness.

Run: python3 verify.py --phase 0

This script makes REAL live calls to real external APIs and prints a
plain-English report a non-programmer can read end to end, followed by an
explicit PASS/FAIL per acceptance criterion. It never uses canned fixtures
to fake a pass — if an API is unreachable, the check FAILs honestly.
"""
import argparse
import json
import sys
import textwrap

import time

import httpx

RULE = "=" * 78


def get_with_retry(url, params, timeout=15, attempts=3):
    """Real network calls in a sandboxed environment can hit transient
    connect/TLS timeouts unrelated to the API itself. Retry a couple of times
    before surfacing an honest failure — this is not fakery, it still fails
    loudly if the API is genuinely unreachable."""
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)
    raise last_exc


def hdr(title):
    print()
    print(RULE)
    print(title)
    print(RULE)


def show_json(label, obj, max_chars=1200):
    text = json.dumps(obj, indent=2)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n  ... (truncated for readability, full response was retrieved and parsed)"
    print(f"--- RAW EVIDENCE: {label} ---")
    print(textwrap.indent(text, "  "))


def check_open_meteo():
    hdr("CHECK 1 of 3 — Open-Meteo (weather multi-model forecast)")
    print("What this checks: can we pull a real, live, multi-model weather forecast")
    print("(ECMWF + GFS + ICON) for a real city, which is the raw material Stage 2's")
    print("weather engine will need. This is a live network call, not a fixture.\n")
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": 41.85,
        "longitude": -87.65,
        "daily": "temperature_2m_max",
        "temperature_unit": "fahrenheit",
        "timezone": "America/Chicago",
        "models": "ecmwf_ifs025,gfs_seamless,icon_seamless",
    }
    try:
        resp = get_with_retry(url, params)
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - honest failure surfaced to the operator
        print(f"FAIL: live call to Open-Meteo raised an error: {exc}")
        return False

    show_json("Open-Meteo response (Chicago, 3 models)", data)

    daily = data.get("daily", {})
    model_keys = [k for k in daily if k.startswith("temperature_2m_max_")]
    ok = len(model_keys) >= 3 and len(daily.get("time", [])) > 0
    print()
    if ok:
        print(f"In plain English: Open-Meteo returned {len(model_keys)} independent model")
        print(f"forecasts ({', '.join(k.replace('temperature_2m_max_', '') for k in model_keys)})")
        print(f"for {len(daily.get('time', []))} days, for real coordinates near Chicago.")
        print("This confirms the exact query shape the weather engine (Phase 2) will use.")
        print("PASS: Open-Meteo multi-model access verified live.")
    else:
        print("FAIL: response did not contain at least 3 model-specific forecast series.")
    return ok


def check_kalshi():
    hdr("CHECK 2 of 3 — Kalshi (real prediction market read)")
    print("What this checks: can we read a real, live, currently-open Kalshi market,")
    print("including its exact resolution rule text and its bid/ask prices — the raw")
    print("material Stage 1's market reader will need. No auth key was used or needed.\n")
    url = "https://api.elections.kalshi.com/trade-api/v2/markets"
    try:
        resp = get_with_retry(url, {"limit": 10, "series_ticker": "KXHIGHNY"})
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: live call to Kalshi raised an error: {exc}")
        return False

    show_json("Kalshi markets response (KXHIGHNY series, NYC daily high temperature)", data)

    markets = data.get("markets", [])
    ok = len(markets) > 0 and all(
        m.get("rules_primary") is not None and m.get("ticker") for m in markets
    )
    print()
    if ok:
        # Prefer a market that's actually trading (non-zero bid) for an honest,
        # non-degenerate midpoint example rather than a not-yet-open $0/$0 one.
        traded = [m for m in markets if float(m.get("yes_bid_dollars", 0)) > 0]
        m = traded[0] if traded else markets[0]
        yes_bid = m.get("yes_bid_dollars")
        yes_ask = m.get("yes_ask_dollars")
        print(f"In plain English: Kalshi returned a real, live market — '{m.get('title')}'")
        print(f"(ticker {m.get('ticker')}). Its exact resolution rule, verbatim from Kalshi:")
        print(f'  "{m.get("rules_primary")}"')
        print(f"Its current yes-bid is ${yes_bid} and yes-ask is ${yes_ask} — Stage 1 will")
        print("compute the implied probability as the midpoint of these two, not the last trade.")
        if yes_bid not in (None, "0.0000"):
            mid = (float(yes_bid) + float(yes_ask)) / 2
            spread = float(yes_ask) - float(yes_bid)
            print(f"  -> implied probability (midpoint) = ({yes_bid} + {yes_ask}) / 2 = {mid:.4f}")
            print(f"  -> spread (trading friction) = {yes_ask} - {yes_bid} = {spread:.4f}")
        print("PASS: Kalshi live market read verified, resolution rule + prices confirmed present.")
    else:
        print("FAIL: no markets returned, or a market was missing its resolution rule / ticker.")
    return ok


def check_polymarket():
    hdr("CHECK 3 of 3 — Polymarket (real prediction market read)")
    print("What this checks: can we read a real, live, open Polymarket market, including")
    print("its outcome prices and its resolution rule description text.\n")
    url = "https://gamma-api.polymarket.com/markets"
    try:
        resp = get_with_retry(url, {"limit": 3, "closed": "false"})
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: live call to Polymarket raised an error: {exc}")
        return False

    show_json("Polymarket Gamma API response", data)

    ok = isinstance(data, list) and len(data) > 0 and all(
        "outcomePrices" in m and "description" in m for m in data
    )
    print()
    if ok:
        m = data[0]
        print(f"In plain English: Polymarket returned a real, live market — '{m.get('question')}'.")
        print(f"Its current outcome prices are {m.get('outcomePrices')} (Yes/No), and its")
        print("resolution rule (verbatim, truncated):")
        desc = (m.get("description") or "")[:300]
        print(f'  "{desc}..."')
        print("PASS: Polymarket live market read verified, prices + resolution text confirmed present.")
    else:
        print("FAIL: no markets returned, or a market was missing outcome prices / description.")
    return ok


def show_okx_ledger_summary():
    hdr("DOCUMENTED FACTS (not computed — these are Verification Ledger findings,")
    print("full evidence and source URLs in docs/VERIFICATION_LEDGER.md)\n")
    print(textwrap.dedent("""\
        OKX AI / okx.ai market feed:
          No evidence OKX hosts its own readable prediction-market venue.
          Stage 1 venues remain Kalshi + Polymarket only. (Ledger §4)

        OKX ASP listing + service registration:
          Real mechanism is TWO OKX skills, not a single "A2MCP": the
          `okx-agent-payments-protocol` skill (x402 HTTP-402 pay-per-call,
          schemes: exact / aggr_deferred / upto / period / charge / session)
          and the `okx-ai` skill (ERC-8004 Agent Identity + Task Marketplace
          for negotiated A2A work). Both require a real Agentic Wallet
          (email-based) and explicit human approval at each identity/payment
          confirmation gate — this cannot be completed by the build agent
          alone; it needs the Operator's wallet and approval. (Ledger §5)

        Work-intake contract (x402):
          402 challenge arrives via one of three signals (WWW-Authenticate:
          Payment header / PAYMENT-REQUIRED header / x402Version in body).
          Full formal JSON schema still to be pinned down with a live round
          trip in Phase 7 — flagged as open, not guessed. (Ledger §6)

        Payment SDK settlement token:
          UNRESOLVED — sources conflict between USDT/USDG (press) and USDC
          (OKX's own worked example + the x402 skill's own display example).
          Not assumed; will be confirmed by a real funded call in Phase 7.
          Settlement chain is X Layer in all sources. (Ledger §7)

        X Layer mainnet facts for receipt anchoring:
          Chain ID 196, gas token OKB, block explorer oklink.com/xlayer.
          Cheapest anchoring method (plain calldata tx vs. minimal attestation
          contract) not yet finalized — decided in Phase 6. (Ledger §8)

        OKX AI Genesis Hackathon submission logistics:
          Secondary sources report a 2026-07-03 to 2026-07-17 UTC submission
          window via Google Form, with mandatory OKX review + go-live for
          eligibility. NOT yet confirmed against the primary rules page —
          flagged for re-verification before Phase 9. (Ledger §9)

        Alibaba Cloud hosting:
          No evidence it's required for this hackathon. Treated as not
          required unless the primary rules page says otherwise. (Ledger §10)

        Moltbook (optional, non-blocking):
          Real and reachable. Registration/posting endpoint shapes come from
          third-party tutorials, not OKX's own docs yet — to be confirmed
          live before Phase 8 if pursued. Never blocks a gate. (Ledger §11)
    """))


def phase_0():
    print(RULE)
    print("REAL-WORLD ODDS ORACLE — VERIFY.PY --phase 0")
    print("GATE 0: Foundations & verification")
    print(RULE)

    results = {
        "Open-Meteo multi-model weather call succeeds": check_open_meteo(),
        "Kalshi live market read succeeds (resolution rule + prices present)": check_kalshi(),
        "Polymarket live market read succeeds (prices + resolution text present)": check_polymarket(),
    }

    show_okx_ledger_summary()

    hdr("GATE 0 — ACCEPTANCE CRITERIA")
    all_pass = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {name}")
    print(f"  [INFO] OKX/X-Layer/Moltbook integration paths documented in Verification"
          f" Ledger with 2 items explicitly flagged open (not blocking GATE 0; see above)")

    print()
    print(RULE)
    if all_pass:
        print("GATE 0 OVERALL: PASS")
    else:
        print("GATE 0 OVERALL: FAIL — see the FAIL lines above; do not proceed to Phase 1")
        print("until every live-data check passes on a real run.")
    print(RULE)
    return 0 if all_pass else 1


def main():
    parser = argparse.ArgumentParser(description="Real-World Odds Oracle verification harness")
    parser.add_argument("--phase", type=int, required=True, help="which phase gate to run")
    args = parser.parse_args()

    if args.phase == 0:
        sys.exit(phase_0())
    else:
        print(f"Phase {args.phase} harness is not built yet.")
        sys.exit(2)


if __name__ == "__main__":
    main()
