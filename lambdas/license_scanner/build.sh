#!/usr/bin/env bash
# Build the Lambda deployment zip for the ohmgym license scanner.
#
# Output: lambdas/license_scanner/build/handler.zip
# Contents: handler.py + scripts/licenses clients + config JSON + requests.
# boto3 is provided by the Lambda runtime (Python 3.12).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BUILD="$HERE/build"
ZIP="$BUILD/handler.zip"

rm -rf "$BUILD"
mkdir -p "$BUILD/pkg/config/licenses" "$BUILD/pkg/config/jira"

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

"$BUILD_PY" -m pip install --quiet \
    --target "$BUILD/pkg" \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.12 \
    --only-binary=:all: \
    -r "$HERE/requirements.txt"

cp "$HERE/handler.py" "$BUILD/pkg/handler.py"
cp "$REPO/scripts/licenses/http_util.py" "$BUILD/pkg/http_util.py"
cp "$REPO/scripts/licenses/github_client.py" "$BUILD/pkg/github_client.py"
cp "$REPO/scripts/licenses/linear_client.py" "$BUILD/pkg/linear_client.py"
cp "$REPO/scripts/licenses/jira_client.py" "$BUILD/pkg/jira_client.py"
cp "$REPO/scripts/licenses/row_status.py" "$BUILD/pkg/row_status.py"
cp "$REPO/config/licenses/apps.json" "$BUILD/pkg/config/licenses/apps.json"
cp "$REPO/config/jira/field-mapping.json" "$BUILD/pkg/config/jira/field-mapping.json"

( cd "$BUILD/pkg" && zip -qr9 "$ZIP" . )

echo "Built $ZIP ($(du -h "$ZIP" | cut -f1))"
