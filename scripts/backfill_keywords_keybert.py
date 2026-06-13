#!/usr/bin/env python3
"""Wrapper — logika w services/processor/backfill_keywords_keybert.py"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "services" / "processor"
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / "backfill_keywords_keybert.py"), run_name="__main__")
