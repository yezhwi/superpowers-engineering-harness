#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="https://github.com/yezhwi/superpowers-engineering-harness.git"
RELEASE_API="https://api.github.com/repos/yezhwi/superpowers-engineering-harness/releases/latest"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [vX.Y.Z]" >&2
  exit 2
fi

if [ -e ".agents/skills/engineering-harness" ]; then
  echo "Skill exists: .agents/skills/engineering-harness" >&2
  exit 1
fi

for command in curl git "$PYTHON_BIN" harness; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command missing: $command" >&2
    exit 1
  fi
done

version="${1:-}"
if [ -z "$version" ]; then
  version="$(
    curl -fsSL "$RELEASE_API" | "$PYTHON_BIN" -c '
import json
import sys
value = json.load(sys.stdin).get("tag_name")
if not isinstance(value, str) or not value:
    raise SystemExit("Latest release has no tag_name")
print(value)
'
  )"
fi

source_dir="$(mktemp -d)"
trap 'rm -rf "$source_dir"' EXIT
source_dir="$source_dir/harness"
git clone --depth 1 --branch "$version" "$REPOSITORY" "$source_dir"

for skill in "$source_dir"/skills/*; do
  name="$(basename "$skill")"
  if [ -e ".agents/skills/$name" ]; then
    echo "Skill exists: .agents/skills/$name" >&2
    exit 1
  fi
done

"$PYTHON_BIN" -m pip install "$source_dir"
mkdir -p .agents/skills
cp -R "$source_dir/skills/." .agents/skills/
harness init

echo "Installed Engineering Harness $version for AGY."
