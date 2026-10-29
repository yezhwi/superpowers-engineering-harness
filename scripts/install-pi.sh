#!/usr/bin/env bash
set -euo pipefail

PACKAGE="superpowers-engineering-harness"
REPOSITORY="https://github.com/yezhwi/superpowers-engineering-harness.git"
SUPERPOWERS_SOURCE="git:github.com/obra/superpowers"
PYTHON_BIN="${PYTHON_BIN:-python3}"
INSTALL_ROOT="${HARNESS_INSTALL_ROOT:-$HOME/.local/share/$PACKAGE}"
BIN_DIR="${HARNESS_BIN_DIR:-$HOME/.local/bin}"
LAUNCHER="$BIN_DIR/harness"
REGISTRY="https://registry.npmjs.org/$PACKAGE"

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

mkdir -p "$INSTALL_ROOT" "$BIN_DIR"
INSTALL_ROOT="$(cd "$INSTALL_ROOT" && pwd -P)"
BIN_DIR="$(cd "$BIN_DIR" && pwd -P)"
LAUNCHER="$BIN_DIR/harness"
lock="$INSTALL_ROOT/.install.lock"
lock_owned=0
skills_attempted=0
VENV="$INSTALL_ROOT/venv"
cleanup() {
  local status=$?
  trap - EXIT HUP INT TERM
  if [ "$status" -ne 0 ] && [ "$skills_attempted" -eq 1 ]; then
    echo "Installation failed; CLI/skills may differ. Re-run installer to reconcile." >&2
    echo "CLI entry: $LAUNCHER; retained environment: $VENV" >&2
  fi
  if [ "$lock_owned" -eq 1 ]; then
    rmdir "$lock" || echo "Installer lock retained; inspect before recovery: $lock" >&2
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir "$lock" 2>/dev/null || fail "Installer lock exists: $lock. Inspect prior installer; no automatic lock stealing."
lock_owned=1

if [ -L "$LAUNCHER" ]; then
  VENV="$("$PYTHON_BIN" -c '
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve().parent.parent)
' "$LAUNCHER")"
fi

check_cli() {
  local environment="$1"
  [ -x "$environment/bin/python" ] && [ -x "$environment/bin/harness" ] || return 1
  local installed_version schema_ok
  installed_version="$("$environment/bin/python" -c '
from importlib.metadata import version
print(version("superpowers-engineering-harness"))
' 2>/dev/null)" || return 1
  [ "$installed_version" = "$version" ] || return 1
  # Schema hashes come from the installed distribution, not the source tree.
  schema_ok="$("$environment/bin/python" -c '
from harness.schema_resources import schema_versions
versions = schema_versions()
if not isinstance(versions, dict) or not versions:
    raise SystemExit(1)
for name, digest in versions.items():
    if type(name) is not str or not name.endswith(".schema.json"):
        raise SystemExit(1)
    if type(digest) is not str or len(digest) != 71 or not digest.startswith("sha256:"):
        raise SystemExit(1)
    if any(ch not in "0123456789abcdef" for ch in digest[7:]):
        raise SystemExit(1)
print("schema-resources-ok")
' 2>/dev/null)" || return 1
  [ "$schema_ok" = "schema-resources-ok" ] || return 1
  "$environment/bin/harness" --help </dev/null >/dev/null 2>&1
}

if ! check_cli "$VENV"; then
  mkdir -p "$INSTALL_ROOT/versions"
  # Console scripts embed this absolute interpreter path. Never move this venv.
  VENV="$(mktemp -d "$INSTALL_ROOT/versions/$version.XXXXXXXX")"
  "$PYTHON_BIN" -m venv "$VENV" </dev/null
  "$VENV/bin/python" -m pip install --disable-pip-version-check --no-input \
    "$PACKAGE @ git+$REPOSITORY@$tag" </dev/null
  check_cli "$VENV" || fail "Installed CLI failed version, schema, or launcher verification: $VENV"
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
  skills_attempted=1
  pi install "$SUPERPOWERS_SOURCE" </dev/null
fi

if ! has_source "$target_source"; then
  skills_attempted=1
  pi install "$target_source" </dev/null
fi
while IFS= read -r old_source; do
  [ -z "$old_source" ] && continue
  [ "$old_source" = "$target_source" ] && continue
  skills_attempted=1
  pi remove "$old_source" </dev/null
done < <(
  printf '%s\n' "$packages" | awk '
    $1 ~ /^npm:superpowers-engineering-harness(@[^[:space:]]+)?$/ ||
    $1 ~ /^git:github\.com\/yezhwi\/superpowers-engineering-harness(@[^[:space:]]+)?$/ {
      print $1
    }
  '
)

# Pi configuration and CLI activation are not one transaction. Verify what Pi
# actually installed before switching CLI; never infer success from exit 0 alone.
package_listing="$(pi list </dev/null)"
packages="$(printf '%s\n' "$package_listing" | awk '
  /^User packages:/ { in_user = 1; next }
  in_user && /^[^[:space:]]/ { exit }
  in_user { print }
')"
has_source "$target_source" || fail "Requested Harness skills source missing after installation."
printf '%s\n' "$packages" | awk '
  $1 ~ /^git:github\.com\/obra\/superpowers(@[^[:space:]]+)?$/ { found = 1 }
  END { exit !found }
' || fail "Superpowers source missing after installation."
if ! printf '%s\n' "$packages" | awk -v target="$target_source" '
  ($1 ~ /^npm:superpowers-engineering-harness(@[^[:space:]]+)?$/ ||
   $1 ~ /^git:github\.com\/yezhwi\/superpowers-engineering-harness(@[^[:space:]]+)?$/) &&
   $1 != target { invalid = 1 }
  END { exit invalid }
'; then
  fail "Obsolete Harness skills source remains after installation."
fi

# Stage and replace in the public entry's own filesystem. Only symlinks move;
# installed environments stay at the exact paths used to create console scripts.
"$PYTHON_BIN" -c '
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile

launcher = Path(sys.argv[1])
target = sys.argv[2]

def interrupted(signum, frame):
    raise SystemExit(128 + signum)

for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
    signal.signal(signum, interrupted)

try:
    if os.path.lexists(launcher) and not launcher.is_symlink():
        raise RuntimeError("Refusing to replace non-symlink launcher")
    previous = os.readlink(launcher) if launcher.is_symlink() else None
    directory = Path(tempfile.mkdtemp(prefix=".harness-entry-", dir=launcher.parent))
    retain = False
    try:
        staged = directory / "next"
        backup = Path(directory) / "previous"
        os.symlink(target, staged)
        identity = staged.lstat()
        if previous is not None:
            os.symlink(previous, backup)
        try:
            os.replace(staged, launcher)
            subprocess.run([str(launcher), "--help"], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=30, check=True)
        except BaseException:
            # Retain recovery data by default, including if inspection itself
            # fails. Clear only after confirmed rollback or failed initial move.
            retain = True
            for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
                signal.signal(signum, signal.SIG_IGN)
            current = launcher.lstat() if os.path.lexists(launcher) else None
            if current is not None and (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                if previous is None:
                    launcher.unlink()
                else:
                    os.replace(backup, launcher)
                retain = False
            elif os.path.lexists(staged):
                retain = False
            raise
    finally:
        if retain:
            print(f"CLI recovery links retained: {directory}", file=sys.stderr)
        else:
            shutil.rmtree(directory)
except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
    print(f"Harness CLI activation failed: {exc}", file=sys.stderr)
    raise SystemExit(1)
' "$LAUNCHER" "$VENV/bin/harness" </dev/null

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo "Installed launcher at $LAUNCHER; add $BIN_DIR to PATH."
fi
echo "Installed Engineering Harness $version for Pi. Open a new Pi session to load skills."
