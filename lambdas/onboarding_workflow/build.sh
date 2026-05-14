#!/usr/bin/env bash
# Build the Lambda deployment zip for the ohmgym onboarding workflow.
#
# Output: lambdas/onboarding_workflow/build/handler.zip
# Contents: handler.py + vendored deps from requirements.txt
#   (requests, PyJWT, cryptography). boto3 is provided by the Lambda
#   runtime (Python 3.12), so we don't bundle it.
#
# Re-run this any time handler.py or requirements.txt changes; Terraform's
# local_file data source picks up the rebuilt zip and the function's
# source_code_hash detects the diff on next plan.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD="$HERE/build"
ZIP="$BUILD/handler.zip"

rm -rf "$BUILD"
mkdir -p "$BUILD/pkg"

# Pick a python 3.12 with pip. On macOS the project default is the system
# framework install (matches the Lambda runtime); on CI Linux we fall back to
# whatever `python3` is on PATH (the workflow sets up python 3.12 explicitly).
# Override either default by setting BUILD_PY.
if [[ -z "${BUILD_PY:-}" ]]; then
    if [[ -x "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3" ]]; then
        BUILD_PY="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
    elif command -v python3.12 >/dev/null 2>&1; then
        BUILD_PY="$(command -v python3.12)"
    elif command -v python3 >/dev/null 2>&1; then
        BUILD_PY="$(command -v python3)"
    else
        echo "ERROR: no python3 found on PATH. Set BUILD_PY=/path/to/python3." >&2
        exit 1
    fi
fi
if [[ ! -x "$BUILD_PY" ]]; then
    echo "ERROR: BUILD_PY=$BUILD_PY is not executable." >&2
    exit 1
fi

# Install pinned deps into the package dir, forcing manylinux2014_x86_64
# wheels so native packages (cryptography) work on Lambda's x86_64 Linux
# runtime even when the build host is macOS arm64.
"$BUILD_PY" -m pip install --quiet \
    --target "$BUILD/pkg" \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.12 \
    --only-binary=:all: \
    -r "$HERE/requirements.txt"

# Drop in the handler.
cp "$HERE/handler.py" "$BUILD/pkg/handler.py"

# Create the zip with deterministic ordering for cleaner Terraform diffs.
( cd "$BUILD/pkg" && zip -qr9 "$ZIP" . )

echo "Built $ZIP ($(du -h "$ZIP" | cut -f1))"
