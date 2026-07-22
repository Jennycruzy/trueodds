# TrueOdd 90-Second Demo (browser-only, no server, no wallet)

**One sentence:** TrueOdd independently prices prediction markets, sells that price to AI agents for crypto via x402, and returns a receipt anyone can verify.

**The arc — four beats, three tabs:** what it is → the edge → pay for it → verify it.

Everything on screen is live and genuine. There is **no live payment** in this browser demo — the Playground only surfaces the real `HTTP 402` challenge.

## Before recording

### Open only these three tabs, in order

1. [Markets — coverage & priced rows](https://trueodd.xyz/markets)
2. [Playground](https://trueodd.xyz/playground)
3. [Receipts](https://trueodd.xyz/receipts)

(Keep [Calibration](https://trueodd.xyz/calibration) open in a 4th tab as a **Q&A backup only — do NOT switch to it on camera.** The per-family table shows many families with 0 resolved / "accumulating", which reads as "half-built" in a 90-second clip even though it's just honest. You quote the *aggregate* calibration number out loud instead. Only open this tab if a judge asks "is it accurate?" — see the note after Beat 4.)

### Three things to prep

1. **A market id.** Load `https://api.trueodd.xyz/v1/market-candidates?venue=polymarket&limit=3`, copy the first `"market_id"` (66-char `0x…` hex), confirm `"freshness_status": "fresh"`. Then close that tab — it's not in the demo, it's just where you got the ID.
2. **Your example row.** On `/markets`, in the **Current priced markets** table, pick one row with a big gap between the **Oracle** column (TrueOdd's probability) and the **Implied** column (the market's), and **Actionable = Yes**. Know exactly which row you'll point at. Real current examples: *"high temp in LA >86° on Jul 16"* → Oracle **82.1%** / Implied **3.5%**; *"high temp in NYC <89°"* → Oracle **11.3%** / Implied **97.5%**. Read whatever is live at record time.
3. **Make the Implied column visible.** That table is wide and the **Implied** column can get cut off. Before recording, zoom the browser to ~80% (or widen the window / scroll right) so **Oracle _and_ Implied are both on screen at once** — that side-by-side is your whole payoff shot.

## The script

### Beat 1 — What it is (0–12s) · tab: /markets

**Action:** Start on `/markets`. Point at the **Markets seen** tile and the **Actionable** tile (the first and last of the four tiles).

**Say:**

> "TrueOdd is a probability oracle for prediction markets. In this live scan it's seen [Markets seen] markets, but only [Actionable] clear the bar to be actionable — it only prices events whose outcome is unambiguous, and everything else fails closed."

*(Use the two end tiles — 6,006 seen → 266 actionable is a clean story. Don't narrate all four as a shrinking funnel: "Evaluated" is not smaller than "Priced & included", so that framing is wrong.)*

### Beat 2 — The edge (12–40s) · tab: /markets

**Action:** Scroll to **Current priced markets** and point at your chosen row — the **Oracle** column, the **Implied** column, the **Actionable** flag. This is the payoff. Slow down here. (Make sure both Oracle and Implied are on screen — see prep step 3.)

**Say:**

> "Here's the actual output. Each row is one market. This column, **Oracle**, is TrueOdd's own probability. This one, **Implied**, is what the market is pricing. On this row TrueOdd says [Oracle]%, the market says [Implied]% — that gap is the edge, and because it's big enough it's flagged **Actionable**. That's a real, current disagreement between the model and the market, and it's what an agent pays for."

### Beat 3 — Pay for it (40–65s) · tab: Playground

**Action:**
1. Switch to **Playground**.
2. Command → `rwoo_check_market`. Venue → `polymarket`. Market id → paste your copied value.
3. Click **Run command**. Wait for **`HTTP 402 — payment required`**.

**Say:**

> "So how does an agent buy that price? It asks — and the live API answers with HTTP 402, Payment Required. This isn't an error. It's the x402 payment challenge: the server is quoting a price and asking the agent's wallet to pay. A funded agent resends the same request with a signed payment and gets the priced answer back, plus a receipt."

### Beat 4 — Verify it (65–90s) · tab: Receipts

**Action:** Switch to **Receipts** (the page heading is **"Receipt verification"**). Point at the status line **"Decision ledger verified — [N] records keccak256"** and the **record_hash** box with the **Verify** button.

**Say:**

> "And every answer TrueOdd issues is written to this ledger — you can see it says verified, [N] records right now, keccak256-chained. Edit any past decision and the chain breaks from that point on. So a buyer never has to trust us: they paste their receipt hash here, hit Verify, and confirm it themselves. And it's calibrated — over [1,300] forecasts scored against real outcomes, Brier [0.11] — measured, not asserted. Real edge, paid for with x402, provable end to end."

*(Say the calibration line **while staying on Receipts** — do NOT open the Calibration tab. Quote the **aggregate only** — resolved-forecast count and Brier — because those are your strong, proven numbers. Read them live off the Calibration page beforehand; at last check: ~1,370 resolved, Brier 0.112. Never put the per-family grid on screen — its zeros read as "half-built".)*

## What this demo proves

- **Real output:** TrueOdd's probability vs. the market's, and the edge — live on the public site.
- **The business model:** a genuine x402 `HTTP 402` payment challenge — agents pay crypto for a price.
- **Trust:** a live, hash-chained, verified decision ledger the buyer checks themselves.

## If a judge asks "is it accurate?" (Q&A only — off the clock)

**Now** you open the Calibration tab, and you stay in control of the framing:

1. Lead with the aggregate: *"~1,370 forecasts resolved against real outcomes, 188 independent events, Brier 0.11 — that's the measured accuracy."*
2. If they drill into a family showing 0 resolved / "accumulating": *"Those forecasts are committed and timestamped, but the events haven't settled yet. We don't invent a track record — we wait for the outcome. Weather is what's resolved most, so it carries the number today; economics and sports are accruing."*

That turns the zeros from "half-built" into "disciplined." Never volunteer the per-family grid — only go there if asked.

## If a judge asks "can it trade / place orders?"

*"By design, no — not yet. The execution layer exists but is deliberately gated off until calibration proves out. TrueOdd sells the priced edge and the proof; it doesn't gamble your money on an unproven model."* (The homepage states execution is "optional, gated, currently disabled, non-custodial.")

## Honesty guardrails

- **No live payment happens here.** The Playground has no wallet; it only surfaces the `402` challenge. Never imply the site completed a payment.
- The Receipts beat shows the ledger is verified **as a whole** (N records, chain valid) — you are not verifying one purchased receipt, so don't narrate it as "the receipt from a payment I just made."
- A full live payment → `HTTP 200` → tx hash → specific receipt must be shown as a separate recorded OKX buyer-agent clip. Out of scope here.
- Read the numbers **actually on screen** at record time — they change as data accrues. If your row's edge is small, pick a different row before recording.
