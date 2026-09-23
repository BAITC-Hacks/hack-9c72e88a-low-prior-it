"""Use a fresh, repository-local temp directory, avoiding cross-user Windows ACLs."""

from pathlib import Path
from uuid import uuid4

import pytest

root = Path(__file__).resolve().parents[1]
target = (root / "artifacts" / "tests" / uuid4().hex).resolve()
if not target.is_relative_to(root / "artifacts"):
    raise RuntimeError("Test temporary directory must stay inside repository artifacts")
target.parent.mkdir(parents=True, exist_ok=True)
raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider", "--basetemp", str(target)]))
