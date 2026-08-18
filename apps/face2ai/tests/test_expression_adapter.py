"""Pure helpers of the MediaPipe + EmotiEffLib adapter — testable without the models or the extra."""

import numpy as np

from face2ai_app.adapters.mediapipe_expression import (
    MediaPipeExpressionEngine,
    compact_blendshapes,
    crop_with_margin,
    match_faces,
    pose_from_matrix,
    softmax_scores,
)
from face2ai_app.domain.models import EMOTIONS, FaceBox


def test_softmax_scores_maps_logits_to_labels():
    scores = softmax_scores([0, 0, 0, 0, 5, 0, 0, 0])
    assert max(scores, key=scores.get) == "Happiness" and abs(sum(scores.values()) - 1) < 1e-6
    assert tuple(scores) == EMOTIONS


def test_softmax_scores_is_numerically_stable_for_large_logits():
    scores = softmax_scores([1000, 0, 0, 0, 0, 0, 0, 0])
    assert scores["Anger"] == 1.0 and abs(sum(scores.values()) - 1) < 1e-6


def test_pose_from_identity_is_zero():
    yaw, pitch, roll = pose_from_matrix(np.eye(4))
    assert (round(yaw), round(pitch), round(roll)) == (0, 0, 0)


def test_pose_from_matrix_recovers_yaw():
    theta = np.radians(30)
    m = np.eye(4)
    m[:3, :3] = [[np.cos(theta), 0, np.sin(theta)], [0, 1, 0], [-np.sin(theta), 0, np.cos(theta)]]
    yaw, pitch, roll = pose_from_matrix(m)
    assert (round(yaw), round(pitch), round(roll)) == (30, 0, 0)


def test_match_faces_by_iou():
    boxes = [FaceBox(top=100, right=400, bottom=300, left=200)]
    assert match_faces(boxes, [(210, 110, 390, 290)]) == [0]  # (left, top, right, bottom)
    assert match_faces(boxes, [(0, 0, 10, 10)]) == [None]


def test_match_faces_assigns_each_landmark_face_once():
    boxes = [
        FaceBox(top=100, right=400, bottom=300, left=200),
        FaceBox(top=110, right=410, bottom=310, left=210),  # near-duplicate of the first
        FaceBox(top=0, right=50, bottom=50, left=0),
    ]
    matches = match_faces(boxes, [(210, 110, 390, 290), (0, 0, 50, 50)])
    assert matches == [0, None, 1]
    assert match_faces([], [(0, 0, 10, 10)]) == []
    assert match_faces(boxes, []) == [None, None, None]


def test_compact_blendshapes_filters_and_rounds():
    assert compact_blendshapes([("mouthSmileLeft", 0.951), ("browDownLeft", 0.05), ("_neutral", 0.3)]) == {
        "mouthSmileLeft": 0.95
    }


def test_crop_with_margin_clamps_to_image():
    arr = np.zeros((100, 200, 3), dtype=np.uint8)
    crop = crop_with_margin(arr, FaceBox(top=0, right=200, bottom=100, left=0), margin=0.2)
    assert crop.shape == (100, 200, 3)


def test_crop_with_margin_expands_inner_box():
    arr = np.zeros((300, 300, 3), dtype=np.uint8)
    crop = crop_with_margin(arr, FaceBox(top=100, right=200, bottom=200, left=100), margin=0.2)
    assert crop.shape == (140, 140, 3)


def test_engine_is_unavailable_without_asset(tmp_path):
    engine = MediaPipeExpressionEngine(tmp_path)
    assert engine.available is False
    assert isinstance(engine.availability_reason, str) and engine.availability_reason
    assert engine.analyze(b"x", [FaceBox(top=0, right=10, bottom=10, left=0)]) == [None]
