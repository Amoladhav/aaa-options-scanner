"""Portable entry point. Offline: python3 -I -S run.py demo."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from trading_scanner.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
