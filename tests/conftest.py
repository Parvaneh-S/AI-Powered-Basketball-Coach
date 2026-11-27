"""
Test setup: point the app at a temporary copy of the seed
database, so tests never read or change a real database.

This runs before any test module imports the backend.
"""

import os
import shutil
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

_test_dir = Path(tempfile.mkdtemp(prefix="shotcoach_tests_"))
_test_db = _test_dir / "test_shotcoach.db"

shutil.copy2(ROOT / "data" / "seed_shotcoach.db", _test_db)

os.environ["SHOTCOACH_DB_PATH"] = str(_test_db)
# Provider tests inject fake transports. Never inherit a live coaching key.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["SHOTCOACH_PROVIDER"] = "openai"
os.environ["OPENAI_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
