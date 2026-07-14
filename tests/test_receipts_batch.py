import tempfile
import unittest
from multiprocessing import Process
from pathlib import Path

from rwoo.receipts import AppendOnlyLedger


def _append_worker(path: str, start: int) -> None:
    AppendOnlyLedger(path).append_many([
        ("quote", {"n": start + offset}, None) for offset in range(25)
    ])


class ReceiptBatchTests(unittest.TestCase):
    def test_batch_append_builds_one_valid_contiguous_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = AppendOnlyLedger(Path(tmp) / "ledger.jsonl")
            rows = ledger.append_many([
                ("quote", {"n": 1}, None),
                ("quote", {"n": 2}, None),
                ("forecast", {"n": 3}, None),
            ])
            self.assertEqual([row.sequence for row in rows], [1, 2, 3])
            self.assertEqual(rows[1].prev_hash, rows[0].chain_hash)
            self.assertEqual(ledger.verify()["record_count"], 3)
            self.assertTrue(ledger.verify()["valid"])

    def test_concurrent_process_batches_cannot_fork_the_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "ledger.jsonl")
            workers = [Process(target=_append_worker, args=(path, start))
                       for start in (0, 100, 200, 300)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(10)
                self.assertEqual(worker.exitcode, 0)
            verification = AppendOnlyLedger(path).verify()
            self.assertTrue(verification["valid"])
            self.assertEqual(verification["record_count"], 100)


if __name__ == "__main__":
    unittest.main()
