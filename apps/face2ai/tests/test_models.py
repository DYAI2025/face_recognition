import pytest
from pydantic import ValidationError

from face2ai_app.domain.models import EMOTIONS, Expression, FaceBox, FaceObservation, Presence, PresenceTransition


def test_expression_shape_and_bounds():
    e = Expression(dominant="Happiness", scores={"Happiness": 0.9, "Neutral": 0.1}, valence=0.7, arousal=0.2,
                   blendshapes={"mouthSmileLeft": 0.95}, yaw=3.0, pitch=-2.0, roll=0.5)
    assert e.dominant == "Happiness" and set(e.scores) <= set(EMOTIONS)
    with pytest.raises(ValidationError):
        Expression(dominant="Happiness", scores={"Bogus": 1.0})
    with pytest.raises(ValidationError):
        Expression(dominant="Happiness", scores={"Happiness": 1.0}, valence=2.0)


def test_face_observation_expression_is_optional_and_presence_carries_mood():
    box = FaceBox(top=1, right=2, bottom=3, left=0)
    assert FaceObservation(box=box).expression is None
    p = Presence(state="KNOWN", mood="Happiness", valence=0.5, arousal=0.1)
    assert p.mood == "Happiness"
    t = PresenceTransition(at="2026-08-18T12:00:00Z", from_state="NO_FACE", to_state="KNOWN")
    assert t.model_dump()["mood"] is None
    assert EMOTIONS == ("Anger", "Contempt", "Disgust", "Fear", "Happiness", "Neutral", "Sadness", "Surprise")
