#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="https://github.com/yezhwi/superpowers-engineering-harness.git"
RELEASE_API="https://api.github.com/repos/yezhwi/superpowers-engineering-harness/releases/latest"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SKILLS_DIR="${AGY_SKILLS_DIR:-$HOME/.gemini/antigravity-cli/skills}"

if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [vX.Y.Z]" >&2
  exit 2
fi

for command in curl git "$PYTHON_BIN"; do
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

temp_dir="$(mktemp -d)"
trap 'rm -rf "$temp_dir"' EXIT
source_dir="$temp_dir/harness"
git clone --depth 1 --branch "$version" "$REPOSITORY" "$source_dir"

staged_skills="$temp_dir/skills"
mkdir "$staged_skills"
for skill in "$source_dir"/skills/*; do
  name="$(basename "$skill")"
  if [ ! -f "$skill/SKILL.md" ]; then
    echo "Missing or unreadable skill manifest: $skill/SKILL.md" >&2
    exit 1
  fi
  cp -R "$skill" "$staged_skills/$name"
  rm -f "$staged_skills/$name/SKILL.md"
  cp "$skill/SKILL.md" "$staged_skills/$name/SKILL.md"
  if [ ! -f "$staged_skills/$name/SKILL.md" ] || [ -L "$staged_skills/$name/SKILL.md" ]; then
    echo "Invalid staged skill manifest: $name/SKILL.md" >&2
    exit 1
  fi
done

"$PYTHON_BIN" -m pip install "$source_dir"
mkdir -p "$SKILLS_DIR"
for skill in "$staged_skills"/*; do
  name="$(basename "$skill")"
  rm -rf "$SKILLS_DIR/$name"
  cp -R "$skill" "$SKILLS_DIR/$name"
done

echo "Installed Engineering Harness $version for AGY at $SKILLS_DIR."
