import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_DATA = Path(tempfile.mkdtemp(prefix="oneframe-test-"))
os.environ["ONEFRAME_DATA"] = str(_DATA)
os.environ["ONEFRAME_DB"] = str(_DATA / "test.db")
