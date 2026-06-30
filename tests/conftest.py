# tests/conftest.py — shared test fixtures/constants.
# ROOT pins fixture/view/backend paths to the repo root so collection is not
# CWD-fragile (module-level file reads must not depend on the process CWD).
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
