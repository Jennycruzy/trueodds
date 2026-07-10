from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from rwoo.readers import clubelo


CSV = "Rank,Club,Country,Level,Elo\n1,Arsenal,ENG,1,1900\n" + "".join(
    f"{i},Club {i},ENG,1,{1500+i}\n" for i in range(2, 105)
)


class ClubEloResilienceTests(unittest.TestCase):
    def setUp(self):
        clubelo._CACHE.clear()
        clubelo._CIRCUIT_OPEN_UNTIL = 0

    def test_https_failure_falls_back_to_http_and_persists(self):
        failed = Mock(); failed.raise_for_status.side_effect = RuntimeError("tls")
        good = Mock(text=CSV); good.raise_for_status.return_value = None
        with TemporaryDirectory() as tmp, patch.object(clubelo, "SNAPSHOT_DIR", Path(tmp)), \
                patch("rwoo.readers.clubelo.httpx.get", side_effect=[failed, good]):
            rows = clubelo.fetch_club_elo(date.today(), fallback_days=0)
            self.assertGreaterEqual(len(rows), 100)
            self.assertTrue(list(Path(tmp).glob("*.json")))

    def test_open_circuit_uses_recent_snapshot(self):
        with TemporaryDirectory() as tmp, patch.object(clubelo, "SNAPSHOT_DIR", Path(tmp)):
            rows = clubelo._parse(CSV, date.today())
            clubelo._store(date.today(), rows)
            clubelo._CIRCUIT_OPEN_UNTIL = float("inf")
            self.assertEqual(clubelo.fetch_club_elo()[0]["source_age_days"], 0)


if __name__ == "__main__":
    unittest.main()
