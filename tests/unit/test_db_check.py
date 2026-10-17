"""The pre-start database check prints the host, never the password."""

from __future__ import annotations

import pytest

from app.config.settings import get_settings
from app.database import check


@pytest.fixture(autouse=True)
def _fresh_settings() -> object:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_unknown_host_is_explained(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://owner:s3cret@ep-typo.invalid/neondb?sslmode=require"
    )
    assert check.main() == 1
    out = capsys.readouterr()
    assert "ep-typo.invalid" in out.out
    assert "does not exist" in out.err
    assert "s3cret" not in out.out + out.err


def test_resolvable_host_passes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://owner:s3cret@localhost:5432/db")
    assert check.main() == 0
    assert "host found" in capsys.readouterr().out
