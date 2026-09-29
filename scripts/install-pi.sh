#!/usr/bin/env bash
set -euo pipefail

PACKAGE="superpowers-engineering-harness"
REPOSITORY="https://github.com/yezhwi/superpowers-engineering-harness.git"
SUPERPOWERS_SOURCE="git:github.com/obra/superpowers"
PYTHON_BIN="${PYTHON_BIN:-python3}"
INSTALL_ROOT="${HARNESS_INSTALL_ROOT:-$HOME/.local/share/$PACKAGE}"
VENV="$INSTALL_ROOT/venv"
BIN_DIR="${HARNESS_BIN_DIR:-$HOME/.local/bin}"
LAUNCHER="$BIN_DIR/harness"
REGISTRY="https://registry.npmjs.org/$PACKAGE"
staged_venv=""

cleanup() {
  if [ -n "$staged_venv" ]; then
    rm -rf "$staged_venv"
  fi
}
trap cleanup EXIT

fail() {
  echo "$*" >&2
  exit 1
}

if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [vX.Y.Z|X.Y.Z]" >&2
  exit 2
fi

for command in curl git pi "$PYTHON_BIN"; do
  command -v "$command" >/dev/null 2>&1 || fail "Required command missing: $command"
done

"$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' \
  || fail "Python 3.11 or newer is required."

if [ "$#" -eq 0 ]; then
  latest_json="$(curl -fsSL "$REGISTRY/latest")" \
    || fail "Unable to resolve npm latest for $PACKAGE."
  version="$(printf '%s' "$latest_json" | "$PYTHON_BIN" -c '
import json
import sys
value = json.load(sys.stdin).get("version")
if not isinstance(value, str):
    raise SystemExit("npm latest has no version")
print(value)
')" || fail "Invalid npm latest metadata for $PACKAGE."
else
  version="${1#v}"
fi

if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  fail "Invalid version '$version'; expected X.Y.Z or vX.Y.Z."
fi
tag="v$version"
target_source="npm:$PACKAGE@$version"

curl -fsSL "$REGISTRY/$version" >/dev/null \
  || fail "npm version $PACKAGE@$version does not exist."
git ls-remote --exit-code --tags "$REPOSITORY" "refs/tags/$tag" >/dev/null \
  || fail "Git tag $tag does not exist."

if [ -e "$LAUNCHER" ] && [ ! -L "$LAUNCHER" ]; then
  fail "Refusing to replace non-symlink launcher: $LAUNCHER"
fi

cli_version=""
if [ -x "$VENV/bin/python" ]; then
  cli_version="$("$VENV/bin/python" -c '
from importlib.metadata import version
print(version("superpowers-engineering-harness"))
' 2>/dev/null || true)"
fi

if [ "$cli_version" != "$version" ] || [ ! -x "$VENV/bin/harness" ]; then
  mkdir -p "$INSTALL_ROOT"
  staged_venv="$INSTALL_ROOT/.venv.tmp.$$"
  rm -rf "$staged_venv"
  "$PYTHON_BIN" -m venv "$staged_venv" </dev/null
  "$staged_venv/bin/python" -m pip install --disable-pip-version-check --no-input \
    "$PACKAGE @ git+$REPOSITORY@$tag" </dev/null
  installed_version="$("$staged_venv/bin/python" -c '
from importlib.metadata import version
print(version("superpowers-engineering-harness"))
')"
  [ "$installed_version" = "$version" ] \
    || fail "Installed CLI version $installed_version does not match $version."
  [ -x "$staged_venv/bin/harness" ] \
    || fail "Installed CLI has no harness executable."
fi

package_listing="$(pi list </dev/null)"
packages="$(printf '%s\n' "$package_listing" | awk '
  /^User packages:/ { in_user = 1; next }
  in_user && /^[^[:space:]]/ { exit }
  in_user { print }
')"
has_source() {
  printf '%s\n' "$packages" | awk -v source="$1" '$1 == source { found = 1 } END { exit !found }'
}

if ! printf '%s\n' "$packages" | awk '
  $1 ~ /^git:github\.com\/obra\/superpowers(@[^[:space:]]+)?$/ { found = 1 }
  END { exit !found }
'; then
  pi install "$SUPERPOWERS_SOURCE" </dev/null
fi

if ! has_source "$target_source"; then
  pi install "$target_source" </dev/null
fi
while IFS= read -r old_source; do
  [ -z "$old_source" ] && continue
  [ "$old_source" = "$target_source" ] && continue
  pi remove "$old_source" </dev/null
done < <(
  printf '%s\n' "$packages" | awk '
    $1 ~ /^npm:superpowers-engineering-harness(@[^[:space:]]+)?$/ ||
    $1 ~ /^git:github\.com\/yezhwi\/superpowers-engineering-harness(@[^[:space:]]+)?$/ {
      print $1
    }
  '
)

if [ -n "$staged_venv" ]; then
  backup="$INSTALL_ROOT/.venv.backup.$$"
  rm -rf "$backup"
  if [ -e "$VENV" ]; then
    mv "$VENV" "$backup"
  fi
  if ! mv "$staged_venv" "$VENV"; then
    if [ -e "$backup" ]; then
      mv "$backup" "$VENV"
    fi
    fail "Unable to activate Harness CLI environment."
  fi
  staged_venv=""
  rm -rf "$backup"
fi

mkdir -p "$BIN_DIR"
ln -sfn "$VENV/bin/harness" "$LAUNCHER"

if ! "$VENV/bin/python" -c '
from importlib.metadata import version
print(version("superpowers-engineering-harness"))
' | grep -qx "$version"; then
  fail "Harness CLI verification failed."
fi

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo "Installed launcher at $LAUNCHER; add $BIN_DIR to PATH."
fi
echo "Installed Engineering Harness $version for Pi. Open a new Pi session to load skills."
