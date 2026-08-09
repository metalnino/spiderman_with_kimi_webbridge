"""Run full unittest suite; exit 0 only if all pass."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    # Prefer consolidated suite if present
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("\n=== SUMMARY ===")
    print(f"ran={result.testsRun} failures={len(result.failures)} errors={len(result.errors)} skipped={len(result.skipped)}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
