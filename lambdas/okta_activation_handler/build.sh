#!/usr/bin/env bash
# Build the Lambda deployment zip for the Okta event hook handler.
#
# Output: lambdas/okta_activation_handler/build/handler.zip
# Contents: handler.py + vendored deps from requirements.txt (requests).
#
# boto3 is provided by the Lambda runtime (Python 3.12), so we don't bundle it.
# Re-run this any time handler.py or requirements.txt changes; Terraform's
# archive_file data source picks up the rebuilt zip automatically on next plan.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD="$HERE/build"
ZIP="$BUILD/handler.zip"

rm -rf "$BUILD"
mkdir -p "$BUILD/pkg"

# Pick a python with pip. The project's .venv ships without pip, so prefer the
# system 3.12 framework python (matches the Lambda runtime). Override by
# setting BUILD_PY to a different interpreter if needed.
BUILD_PY="${BUILD_PY:-/Library/Frameworks/Python.framework/Versions/3.12/bin/python3}"
if [[ ! -x "$BUILD_PY" ]]; then
    echo "ERROR: $BUILD_PY not found. Set BUILD_PY=/path/to/python3 with pip available." >&2
    exit 1
fi

# Install pinned deps into the package dir, forcing manylinux2014_x86_64
# wheels so native packages (cryptography, etc.) work on Lambda's x86_64
# Linux runtime even when the build host is macOS arm64.
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
