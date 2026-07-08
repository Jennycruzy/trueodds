"""Receipt commitments and append-only ledger.

Phase 6 local integrity is fully deterministic: canonical JSON -> SHA3-256
record hash -> hash chain. X Layer anchoring should go through the verified OKX
Agentic Wallet path; the verification harness reports that prerequisite
honestly instead of pretending a local hash is an on-chain anchor.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HASH_ALGORITHM = "sha3_256_local_commitment"
GENESIS_PREV_HASH = "0" * 64


@dataclass(frozen=True)
class ReceiptRecord:
    sequence: int
    record_type: str
    payload: dict[str, Any]
    created_at: str
    prev_hash: str
    record_hash: str
    chain_hash: str
    hash_algorithm: str = HASH_ALGORITHM
    anchor: dict[str, Any] | None = None


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def hash_hex(value: Any) -> str:
    return hashlib.sha3_256(canonical_json(value).encode("utf-8")).hexdigest()


def make_receipt_payload(
    *,
    venue: str,
    market_id: str,
    resolution_rule: str,
    oracle_prob: float,
    implied_prob: float,
    edge: dict[str, Any],
    confidence: float | None,
    sources: dict[str, Any],
    timestamp: str | None = None,
) -> dict[str, Any]:
    return {
        "venue": venue,
        "market_id": market_id,
        "resolution_rule": resolution_rule,
        "oracle_prob": oracle_prob,
        "implied_prob": implied_prob,
        "edge": edge,
        "confidence": confidence,
        "sources": sources,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
    }


class AppendOnlyLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def read_records(self) -> list[ReceiptRecord]:
        if not self.path.exists():
            return []
        records = []
        for line_no, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                records.append(ReceiptRecord(**raw))
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"ledger line {line_no} is not a valid receipt record: {exc}") from exc
        return records

    def append(self, record_type: str, payload: dict[str, Any], anchor: dict[str, Any] | None = None) -> ReceiptRecord:
        records = self.read_records()
        sequence = len(records) + 1
        prev_hash = records[-1].chain_hash if records else GENESIS_PREV_HASH
        created_at = datetime.now(timezone.utc).isoformat()
        record_hash = hash_hex(
            {
                "sequence": sequence,
                "record_type": record_type,
                "payload": payload,
                "created_at": created_at,
                "prev_hash": prev_hash,
                "hash_algorithm": HASH_ALGORITHM,
            }
        )
        chain_hash = hash_hex({"prev_hash": prev_hash, "record_hash": record_hash})
        record = ReceiptRecord(
            sequence=sequence,
            record_type=record_type,
            payload=payload,
            created_at=created_at,
            prev_hash=prev_hash,
            record_hash=record_hash,
            chain_hash=chain_hash,
            anchor=anchor,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(canonical_json(asdict(record)) + "\n")
        return record

    def verify(self) -> dict[str, Any]:
        records = self.read_records()
        prev_hash = GENESIS_PREV_HASH
        for expected_sequence, record in enumerate(records, start=1):
            if record.sequence != expected_sequence:
                return {
                    "valid": False,
                    "reason": f"sequence break at record {expected_sequence}: found {record.sequence}",
                    "record": expected_sequence,
                }
            if record.prev_hash != prev_hash:
                return {
                    "valid": False,
                    "reason": f"prev_hash mismatch at record {expected_sequence}",
                    "record": expected_sequence,
                }
            expected_record_hash = hash_hex(
                {
                    "sequence": record.sequence,
                    "record_type": record.record_type,
                    "payload": record.payload,
                    "created_at": record.created_at,
                    "prev_hash": record.prev_hash,
                    "hash_algorithm": record.hash_algorithm,
                }
            )
            if record.record_hash != expected_record_hash:
                return {
                    "valid": False,
                    "reason": f"record_hash mismatch at record {expected_sequence}",
                    "record": expected_sequence,
                }
            expected_chain_hash = hash_hex({"prev_hash": record.prev_hash, "record_hash": record.record_hash})
            if record.chain_hash != expected_chain_hash:
                return {
                    "valid": False,
                    "reason": f"chain_hash mismatch at record {expected_sequence}",
                    "record": expected_sequence,
                }
            prev_hash = record.chain_hash
        return {
            "valid": True,
            "record_count": len(records),
            "head_hash": prev_hash if records else GENESIS_PREV_HASH,
            "hash_algorithm": HASH_ALGORITHM,
        }
