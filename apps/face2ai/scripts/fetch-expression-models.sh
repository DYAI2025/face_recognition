#!/usr/bin/env bash
# Fetch the MediaPipe Face Landmarker asset (3.7 MB) into $FACE2AI_EXPRESSION_MODELS_DIR (default ~/.face2ai/models).
# EmotiEffLib downloads its ONNX model on first use into its own cache.
set -euo pipefail
DIR="${FACE2AI_EXPRESSION_MODELS_DIR:-$HOME/.face2ai/models}"
mkdir -p "$DIR"
[ -f "$DIR/face_landmarker.task" ] || curl -sS -L -o "$DIR/face_landmarker.task" \
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
ls -la "$DIR/face_landmarker.task"
