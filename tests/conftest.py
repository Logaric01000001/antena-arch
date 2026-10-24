import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakeenv import FakeEnvironment  # noqa: E402


@pytest.fixture()
def env(tmp_path: Path) -> FakeEnvironment:
    return FakeEnvironment(tmp_path)
