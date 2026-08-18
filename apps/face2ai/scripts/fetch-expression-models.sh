#!/usr/bin/env bash
# Fetch the MediaPipe Face Landmarker asset (3.7 MB) into $FACE2AI_EXPRESSION_MODELS_DIR
# (default: $FACE2AI_DATA_DIR/models, i.e. ~/.face2ai/models — same derivation as Settings.from_env).
# EmotiEffLib downloads its ONNX model on first use into its own cache.
set -euo pipefail
DIR="${FACE2AI_EXPRESSION_MODELS_DIR:-${FACE2AI_DATA_DIR:-$HOME/.face2ai}/models}"
URL="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
mkdir -p "$DIR"
if [ ! -f "$DIR/face_landmarker.task" ]; then
  # fail-fast (-f: HTTP errors are errors) and atomic (download to .part, then rename)
  curl -fsSL -o "$DIR/face_landmarker.task.part" "$URL" && mv "$DIR/face_landmarker.task.part" "$DIR/face_landmarker.task"
fi
ls -la "$DIR/face_landmarker.task"
