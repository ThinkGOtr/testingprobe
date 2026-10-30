"""golden-drift paketi: core venv'i olmadan, saf veri olarak koşar (anayasa II)."""

import sys
from pathlib import Path

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
