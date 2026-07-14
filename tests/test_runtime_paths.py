import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimePathTests(unittest.TestCase):
    def _probe(self, module: str, names: list[str], extra_env: dict[str, str]) -> list[str]:
        code = (
            f"import {module} as target; "
            f"print('|'.join(str(getattr(target, name)) for name in {names!r}))"
        )
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), **extra_env}
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, env=env,
            check=True, capture_output=True, text=True,
        )
        return result.stdout.strip().split("|")

    def test_scanner_and_evidence_honor_shared_runtime_paths(self):
        scan = self._probe("rwoo.scanner", ["DEFAULT_SCAN_JSON", "DEFAULT_SCAN_MD"], {
            "RWOO_OPPORTUNITY_SCAN_PATH": "/var/lib/rwoo/public/scan.json",
            "RWOO_OPPORTUNITY_SCAN_MD_PATH": "/var/lib/rwoo/public/scan.md",
        })
        evidence = self._probe(
            "rwoo.evidence", ["DEFAULT_LEDGER", "DEFAULT_REPORT", "DEFAULT_REPORT_MD", "DEFAULT_BACKLOG"], {
                "RWOO_EVIDENCE_LEDGER_PATH": "/var/lib/rwoo/receipts/evidence.jsonl",
                "RWOO_CALIBRATION_REPORT_PATH": "/var/lib/rwoo/public/calibration.json",
                "RWOO_CALIBRATION_REPORT_MD_PATH": "/var/lib/rwoo/public/calibration.md",
            },
        )
        edge_audit = self._probe("rwoo.edge_audit", ["DEFAULT_SCAN", "DEFAULT_AUDIT"], {
            "RWOO_OPPORTUNITY_SCAN_PATH": "/var/lib/rwoo/public/scan.json",
        })
        self.assertEqual(scan, ["/var/lib/rwoo/public/scan.json", "/var/lib/rwoo/public/scan.md"])
        self.assertEqual(evidence, [
            "/var/lib/rwoo/receipts/evidence.jsonl",
            "/var/lib/rwoo/public/calibration.json",
            "/var/lib/rwoo/public/calibration.md",
            "/var/lib/rwoo/public/evidence_backlog_latest.json",
        ])
        self.assertEqual(edge_audit, [
            "/var/lib/rwoo/public/scan.json",
            "/var/lib/rwoo/public/opportunity_scan_edge_audit_latest.json",
        ])

    def test_worker_units_load_shared_environment_and_state(self):
        unit_paths = [
            ROOT / "deploy/systemd/rwoo-evidence.service",
            ROOT / "deploy/systemd/rwoo-closing-quotes.service",
            ROOT / "deploy/systemd/rwoo-closing-quotes-near.service",
            ROOT / "deploy/systemd/rwoo-scan.service.d/hardening.conf",
            ROOT / "deploy/systemd/rwoo-api.service.d/shared-state.conf",
            ROOT / "deploy/systemd/rwoo-site.service.d/shared-state.conf",
        ]
        for path in unit_paths:
            text = path.read_text(encoding="utf-8")
            self.assertIn("EnvironmentFile=-/etc/rwoo/rwoo-release.env", text, path.name)
            self.assertIn("ReadWritePaths=/var/lib/rwoo /var/cache/rwoo", text, path.name)


if __name__ == "__main__":
    unittest.main()
