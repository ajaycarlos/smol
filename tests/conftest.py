import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.make_samples import (  # noqa: E402
    DEFAULT_SAMPLES_DIR,
    GENERATORS,
    PDF_GENERATORS,
    generate_all_samples,
)


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    """Fixture that generates test samples on demand into tests/samples/.

    Reuses already generated samples if all expected files are present.
    """
    DEFAULT_SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    all_expected = list(GENERATORS) + list(PDF_GENERATORS)
    missing = [f for f in all_expected if not (DEFAULT_SAMPLES_DIR / f).exists()]
    if missing:
        generate_all_samples(DEFAULT_SAMPLES_DIR)
    return DEFAULT_SAMPLES_DIR


@pytest.fixture(autouse=True)
def isolate_test_config(tmp_path_factory, monkeypatch):
    """Ensure test runs never touch the user's real ~/.config/smol/config.toml."""
    test_config_dir = tmp_path_factory.mktemp("test_config")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(test_config_dir))


@pytest.fixture
def qapp():
    """Ensure a QApplication instance exists for GUI component tests."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(["smol-test"])
    yield app
