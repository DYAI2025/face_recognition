from pathlib import Path

from face2ai_app.config import Settings


def test_expression_settings_have_safe_defaults(monkeypatch):
    monkeypatch.delenv("FACE2AI_EXPRESSION_ENABLED", raising=False)
    monkeypatch.delenv("FACE2AI_EXPRESSION_MODELS_DIR", raising=False)
    settings = Settings.from_env()
    assert settings.expression_enabled is False  # opt-in
    assert settings.expression_models_dir == Path.home() / ".face2ai" / "models"
    assert settings.mood_stable_ticks == 3
    assert settings.mood_min_score == 0.5


def test_expression_settings_read_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FACE2AI_EXPRESSION_ENABLED", "true")
    monkeypatch.setenv("FACE2AI_EXPRESSION_MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("FACE2AI_MOOD_STABLE_TICKS", "5")
    settings = Settings.from_env()
    assert settings.expression_enabled is True
    assert settings.expression_models_dir == tmp_path
    assert settings.mood_stable_ticks == 5
