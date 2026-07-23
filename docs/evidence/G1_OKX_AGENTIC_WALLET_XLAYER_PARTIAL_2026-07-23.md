# G1 — OKX Agentic Wallet X Layer bridge (partial)

Date: 2026-07-23

## Result

Funding-route success; full execution certification remains partial. The OKX
Agentic Wallet autonomously approved and submitted an X Layer USD₮0 bridge
transaction through the OKX/MESON route. The source transaction succeeded,
2.5 USD₮0 left the wallet, OKX later reported bridge `SUCCESS`, and the
caller-owned Polymarket deposit wallet received `2.391351 pUSD` on Polygon.

Do not mark the backend `executable` yet: the OKX Agentic Wallet L2 credential
and ERC-1271/ERC-7739 order-signing path, signed SELL path, and persistent
position reconciliation still require certification. Do not send another
bridge transaction for this test.

## Wallet and route

- Login identity: `kingsjanet0@gmail.com`
- Owner EVM/X Layer wallet: `0x48ddC64e362e337b1eaEA67486A9F8c2869eAF38`
- Beacon-derived Polymarket deposit wallet:
  `0x577108052c8D862984B724668E2f6035Eb6Fa5c5`
- Polymarket bridge receiver:
  `0xf4689cc91e2b2295d31d3c66d548f3e413c9cef2`
- Source: X Layer USD₮0
  `0x779ded0c9e1022225f8e0630b35a9b54be713736`
- Route: X Layer USD₮0 -> Polygon USDT, MESON bridge ID `223`
- Input: `2.5` USD₮0
- Quoted output/minimum output: `2.4` USDT
- Quoted fee: `0.1` USDT
- Geoblock check: `{"blocked":false}`

The receiver intentionally differs from the sender: it is the verified,
beacon-derived Polymarket deposit address for this owner. It was not an arbitrary
destination.

## Direct execute limitation

Both the direct cross-chain execute call and the unsigned cross-chain builder
rejected the Agentic Wallet address with API code `82110`:
`not support AA wallet address`.

Same-chain Agentic Wallet swaps worked, showing this is specific to the
cross-chain builder/execute address validation rather than a general inability
to execute transactions.

## Autonomous workaround exercised

The route was built using a plain EOA as the builder-only sender parameter. The
returned MESON calldata did not embed that placeholder address. The real
Agentic Wallet then executed the required calls itself with
`wallet contract-call`; the ASP did not receive or custody a key.

1. Exact 2.5 USD₮0 approval to MESON:
   - Agentic Wallet order ID: `1808471368803221568`
   - Transaction:
     `0x897d07d3b836b8d9b3eca56e06e6e8d78eb7e78496df583a60f76d09cf94db17`
   - Wallet history status: `SUCCESS`
2. MESON bridge call:
   - Agentic Wallet order ID: `1808495695498068027`
   - Transaction:
     `0x4008e6a2809071ebf59b6ba238121923a41c411b3ab4c219c46f9906ceb73843`
   - Source-chain wallet history status: `SUCCESS`

Security scans found no actionable approval or bridge-call risk. Before approval,
simulation correctly failed at `transferFrom`; after approval the final scan did
not report that revert.

## Confirmed destination settlement

The existing bridge transaction was checked again without resending. OKX
cross-chain status returned:

- status: `SUCCESS`
- reported destination amount: `2.4`
- destination transaction:
  `0x48189759376aa9597c877aecdded0642a7f525413dc54058c06e2b003af75e20`

The Polygon transaction receipt has status `0x1`. A direct `balanceOf` call to
the pUSD contract
`0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB` returned `2391351` base units
for the caller deposit wallet, or `2.391351 pUSD`. The difference from the
2.5 USD₮0 input consists of the quoted MESON cost and final
bridge/conversion costs.

The last recorded X Layer wallet balances after the source debit were:
  - `1.719665` USD₮0
  - `0.000245` legacy USDT
  - `0.006` OKB

This proves the autonomous caller-owned funding route:
X Layer USD₮0 -> OKX/MESON -> Polygon USDT -> Polymarket bridge -> pUSD in the
caller's deposit wallet. The wallet remains below the X Layer 2.5-token route
minimum, and this completed transfer must not be retried.

## Supporting same-chain tests

- USD₮0 -> legacy X Layer USDT:
  `0xe97020c53c0ebb0974236016a09448aa824497bd4c4cae5575f64edf87e645cb`
- Legacy X Layer USDT -> USD₮0:
  `0x9be7062a6ddd444ef436621942f6f13117e2e6d30bed7f153b8d8ca73afac14f`

Legacy X Layer USDT had no usable MESON liquidity in the tested route. Converting
to legacy USDT first is therefore not the demonstrated workaround.

## Signing progress

The following caller-side primitives are now proven without browser
confirmation or a private key:

- `onchainos wallet sign-message --type eip712 --force` returned a valid ECDSA
  signature with exit code zero.
- The signature recovered to the Agentic Wallet owner using the same digest as
  the Polymarket SDK.
- CLOB L2 credential creation returned HTTP 200 with complete credentials.
- L2 HMAC authentication succeeded after using the exact serialized request.
- The nested `TypedDataSign` EIP-712 digest matches the SDK's ERC-7739
  computation.

No signature or credential value is recorded here.

## Deposit-wallet deployment and approval boundary

The caller's beacon-derived deposit wallet is now deployed:

- relayer transaction ID:
  `019f9000-8958-7484-ae32-04b2e7003d64`
- Polygon transaction:
  `0x055ab76765d34382f143fa098d55e42984c40809576d630ad1232263b00b5947`
- final relayer state: `STATE_CONFIRMED`

On-chain bytecode now exists at
`0x577108052c8D862984B724668E2f6035Eb6Fa5c5`, and its immutable owner is the
Agentic Wallet address. The `2.391351 pUSD` balance remains in that wallet.

A bounded approval of `0.1 pUSD` to Exchange V2 was signed non-interactively,
but Polymarket's relayer rejected it before submission:

`approve to exchange 0xE111180000d2663C0091e4f400237545B87B996B must be MaxUint256`

The allowance remains zero. TrueOdds will not substitute an unlimited approval:
that would give the exchange drain-level authority over all present and future
pUSD in the deposit wallet. The next safe investigation is whether the deployed
wallet permits a directly relayed bounded batch outside the policy-enforcing
Polymarket relayer. Order acceptance and cancellation remain unproven for the
Agentic Wallet backend.

That direct bounded investigation is now complete:

- The live deposit wallet implementation is
  `0xf7f27C29e60fe6325beF8dA7F93250353d2e3294`.
- Calling the wallet's signed `execute(...)` entrypoint directly reverted with
  `OnlyFactory()`.
- The factory is
  `0x00000000000fb5c9adea0298d729a0cb3823cc07`; its live implementation is
  `0x528cc05efac2b0d255e423272187efd41248abd7`.
- A read-only simulation of the signed bounded `0.1 pUSD` approval through the
  factory's `proxy(...)` entrypoint succeeded when the caller was the
  Polymarket relayer operator.
- The identical simulation from the Agentic Wallet owner reverted with
  `OnlyOperator()`.

Therefore `MaxUint256` is not required by pUSD, the deposit wallet, or the
factory contract. It is an off-chain rule imposed by Polymarket's hosted
relayer. A bounded approval is contract-valid, but only a factory-authorized
operator can broadcast it. TrueOdds cannot make that path autonomous without
Polymarket changing the hosted-relayer policy or authorizing a TrueOdds
operator.

Builder authentication is a TrueOdds integration responsibility, not a buyer
credential. An ordinary buyer L2 key received HTTP 403 from
`POST /auth/builder-api-key`; the registered TrueOdds builder identity
successfully authenticated the wallet deployment. Production must keep builder
credentials server-side or behind a remote builder signer and never ship them
to buyer agents.

## Minimum correction

The `2.5` minimum applies to the tested X Layer USDT/USD₮0 bridge path. It must
not be applied globally to normal EVM/Polygon Polymarket deposit routes, which
have no corresponding minimum in this implementation.
