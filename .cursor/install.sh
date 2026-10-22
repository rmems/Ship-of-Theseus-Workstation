#!/usr/bin/env bash
# Cursor Cloud Agent install script for Ship-of-Theseus-Workstation (`install` in .cursor/environment.json).
#
# Cursor runs this from the repository root during every Build, on its default
# Ubuntu base image (CPU only: cloud agents have no GPU), then snapshots the disk.
# It must be idempotent. Shell exports don't survive into agent runs, so the tools
# it installs are exposed through /etc/profile.d and /usr/local/bin.
# See https://cursor.com/docs/cloud-agent/setup
#
# Installs only what this repo's CI and manifests need:
#   - apt: curl, ca-certificates
#   - uv + Python 3.13 venv with requirements.txt
#   - ShellCheck 0.11.0 (pinned tarball + sha256, as in portable-ci.yml)
#   - tool directories exposed to later shells (/etc/profile.d + /usr/local/bin links)
#
# It ends with a dependency fetch/prebuild, not a test run.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
fi

# Install apt packages that are not already present.
apt_install() {
  local missing=() pkg
  for pkg in "$@"; do
    if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
      missing+=("$pkg")
    fi
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    $SUDO apt-get -o Acquire::Retries=5 update -qq
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=5 install -y --no-install-recommends "${missing[@]}"
  fi
}

# --- System packages (curl + CA certs for the installers below) ---
apt_install curl ca-certificates

# --- Python (uv) ---
UV_VERSION=0.6.14
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1 || ! uv --version 2>/dev/null | grep -qx "uv $UV_VERSION"; then
  uv_tmp="$(mktemp)"
  trap 'rm -f "$uv_tmp"' EXIT
  curl -fsSL --retry 3 -o "$uv_tmp" "https://astral.sh/uv/${UV_VERSION}/install.sh"
  sh "$uv_tmp"
  rm -f "$uv_tmp"
  trap - EXIT
fi
# system-report.yml uses Python 3.13.
if ! uv python install 3.13; then
  echo "error: failed to install Python 3.13" >&2
  exit 1
fi
if [ -x .venv/bin/python ] && ! .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 13) else 1)'; then
  rm -rf .venv
fi
if [ ! -x .venv/bin/python ]; then
  uv venv --seed --python 3.13 .venv
fi
if [ -f requirements.txt ]; then
  uv pip install --python .venv/bin/python -r requirements.txt
fi

# --- ShellCheck 0.11.0 (portable-ci.yml checks the exact version) ---
if ! shellcheck --version 2>/dev/null | grep -qx 'version: 0.11.0'; then
  case "$(uname -m)" in
    x86_64)
      sc_arch=x86_64
      sc_sha256=8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198
      ;;
    aarch64 | arm64)
      sc_arch=aarch64
      sc_sha256=12b331c1d2db6b9eb13cfca64306b1b157a86eb69db83023e261eaa7e7c14588
      ;;
    *)
      echo "error: pinned ShellCheck 0.11.0 has no checksum for $(uname -m)" >&2
      exit 1
      ;;
  esac
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL --retry 3 -o "$tmp/shellcheck.tar.xz" \
    "https://github.com/koalaman/shellcheck/releases/download/v0.11.0/shellcheck-v0.11.0.linux.${sc_arch}.tar.xz"
  echo "${sc_sha256}  $tmp/shellcheck.tar.xz" | sha256sum -c -
  tar -xf "$tmp/shellcheck.tar.xz" -C "$tmp"
  $SUDO install -m 0755 "$tmp/shellcheck-v0.11.0/shellcheck" /usr/local/bin/shellcheck
  rm -rf "$tmp"
  trap - EXIT
fi

# --- Expose the tools to later shells ---
# The PATH exports above last only for this script; Cursor starts the agent's shells
# separately. Login shells get these directories from /etc/profile.d, and every other
# shell finds the entry points through symlinks in /usr/local/bin (on the default PATH).
# In login shells the venv's bin comes first, so python3 is the venv's Python.
# The links skip python and pip; other shells get the python3 wrapper below instead.
repo_root="$(pwd)"
tool_dirs=("$repo_root/.venv/bin" "$HOME/.local/bin")
# shellcheck disable=SC2016 # $HOME and $PATH must expand when the profile is sourced, not now.
printf 'export PATH=%q:${HOME}/.local/bin:$PATH\n' "$repo_root/.venv/bin" |
  $SUDO tee /etc/profile.d/cursor-env-Ship-of-Theseus-Workstation.sh >/dev/null
for dir in "${tool_dirs[@]}"; do
  [ -d "$dir" ] || continue
  for tool in "$dir"/*; do
    name="${tool##*/}"
    case "$name" in
      # uv's installer also drops env/env.fish (sourced, not run) in ~/.local/bin.
      python* | pip* | activate* | deactivate | Activate.ps1 | env | env.fish) continue ;;
    esac
    if [ -f "$tool" ] && [ -x "$tool" ]; then
      $SUDO ln -sfn "$tool" "/usr/local/bin/$name"
    fi
  done
done

# scripts/theseus-report runs `#!/usr/bin/env python3` and needs the venv's jsonschema.
venv_python="$repo_root/.venv/bin/python3"
printf '#!/bin/sh\nif [ ! -x %q ]; then\n  echo "error: venv python missing at %q (re-run the Cursor Build)" >&2\n  exit 1\nfi\nexec %q "$@"\n' \
  "$venv_python" "$venv_python" "$venv_python" |
  $SUDO tee /usr/local/bin/python3 >/dev/null
$SUDO chmod 0755 /usr/local/bin/python3

# .venv/ is not in .gitignore here, so keep it out of `git status`.
exclude_file="$(git rev-parse --git-path info/exclude 2>/dev/null || echo "")"
if [ -n "$exclude_file" ]; then
  mkdir -p "$(dirname "$exclude_file")"
  grep -qxF '/.venv/' "$exclude_file" 2>/dev/null || echo '/.venv/' >>"$exclude_file"
fi

echo "Cursor install for Ship-of-Theseus-Workstation finished."
