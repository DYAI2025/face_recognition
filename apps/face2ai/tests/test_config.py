from pathlib import Path

import pytest

from face2ai_app.config import Settings

_EXPRESSION_ENV = (
    "FACE2AI_EXPRESSION_ENABLED",
    "FACE2AI_EXPRESSION_MODELS_DIR",
    "FACE2AI_MOOD_STABLE_TICKS",
    "FACE2AI_MOOD_MIN_SCORE",
    "FACE2AI_DATA_DIR",
)


def _clear_env(monkeypatch):
    for name in _EXPRESSION_ENV:
        monkeypatch.delenv(name, raising=False)


def test_expression_settings_have_safe_defaults(monkeypatch):
    _clear_env(monkeypatch)
    settings = Settings.from_env()
    assert settings.expression_enabled is False  # opt-in
    assert settings.expression_models_dir == Path.home() / ".face2ai" / "models"
    assert settings.expression_models_dir == settings.data_dir / "models"
    assert settings.mood_stable_ticks == 3
    assert settings.mood_min_score == 0.5


def test_expression_settings_read_env(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("FACE2AI_EXPRESSION_ENABLED", "true")
    monkeypatch.setenv("FACE2AI_EXPRESSION_MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("FACE2AI_MOOD_STABLE_TICKS", "5")
    monkeypatch.setenv("FACE2AI_MOOD_MIN_SCORE", "0.7")
    settings = Settings.from_env()
    assert settings.expression_enabled is True
    assert settings.expression_models_dir == tmp_path
    assert settings.mood_stable_ticks == 5
    assert settings.mood_min_score == 0.7


def test_expression_models_dir_derives_from_data_dir(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("FACE2AI_DATA_DIR", str(tmp_path))
    settings = Settings.from_env()
    assert settings.data_dir == tmp_path
    assert settings.expression_models_dir == tmp_path / "models"


@pytest.mark.parametrize("raw", ["ture", "2", "enabled", "ja"])
def test_expression_enabled_rejects_garbage(monkeypatch, raw):
    _clear_env(monkeypatch)
    monkeypatch.setenv("FACE2AI_EXPRESSION_ENABLED", raw)
    with pytest.raises(ValueError, match="FACE2AI_EXPRESSION_ENABLED must be a boolean"):
        Settings.from_env()


@pytest.mark.parametrize(("raw", "expected"), [("1", True), (" YES ", True), ("On", True),
                                               ("0", False), ("no", False), ("OFF", False), ("", False)])
def test_expression_enabled_accepts_known_spellings(monkeypatch, raw, expected):
    _clear_env(monkeypatch)
    monkeypatch.setenv("FACE2AI_EXPRESSION_ENABLED", raw)
    assert Settings.from_env().expression_enabled is expected


def test_mood_validators_reject_out_of_range():
    with pytest.raises(ValueError, match="FACE2AI_MOOD_STABLE_TICKS"):
        Settings(mood_stable_ticks=0)
    with pytest.raises(ValueError, match="FACE2AI_MOOD_MIN_SCORE"):
        Settings(mood_min_score=0)
    with pytest.raises(ValueError, match="FACE2AI_MOOD_MIN_SCORE"):
        Settings(mood_min_score=1.5)
    assert Settings(mood_min_score=1.0).mood_min_score == 1.0
