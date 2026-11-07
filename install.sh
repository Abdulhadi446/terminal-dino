#!/usr/bin/env bash
# install.sh - install terminal-dino and make `dino` runnable from any shell
# Usage: ./install.sh [--user|--system|--prefix DIR] [--keep-source]

set -euo pipefail

PROG="Terminal Dino"
REPO_URL="${REPO_URL:-https://raw.githubusercontent.com/Abdulhadi446/terminal-dino/main}"

USER_LEVEL=1
PREFIX=""

while (( $# > 0 )); do
  case "$1" in
    --system|-s) USER_LEVEL=0;;
    --user|-u) USER_LEVEL=1;;
    --prefix) shift; PREFIX="${1:?--prefix needs a directory}";;
    --help|-h)
      cat <<'EOF'
Usage: ./install.sh [--user|--system|--prefix DIR]

  --user     install under ~/.local (default)
  --system   install under /usr/local (needs root or sudo)
  --prefix   custom install prefix

After installing, run:  dino
EOF
      exit 0;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
  shift
done

log() { printf 'install: %s\n' "$*"; }
fail() { printf 'install: error: %s\n' "$*" >&2; exit 1; }

# ---- find a suitable Python (>= 3.8) ----
PYTHON_BIN="$(command -v python3 || command -v python || true)"
[[ -z "$PYTHON_BIN" ]] && fail "python 3 is not installed."
if ! "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)'; then
  fail "python 3.8 or newer is required."
fi

# ---- where is dino.py? ----
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_PY=""
for candidate in "$SCRIPT_DIR/dino.py" "$PWD/dino.py"; do
  if [[ -f "$candidate" ]]; then SOURCE_PY="$candidate"; break; fi
done
if [[ -z "$SOURCE_PY" ]]; then
  log "dino.py not found next to the installer; downloading it..."
  TMP_PY="$(mktemp)"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$REPO_URL/dino.py" -o "$TMP_PY"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$TMP_PY" "$REPO_URL/dino.py"
  else
    fail "no dino.py and no curl/wget to download one"
  fi
  SOURCE_PY="$TMP_PY"
fi

# ---- pick install layout ----
if [[ -n "$PREFIX" ]]; then
  BASE_DIR="$PREFIX"
  BIN_DIR="$PREFIX/bin"
else
  if (( USER_LEVEL == 0 )); then
    BASE_DIR="/usr/local"
    BIN_DIR="/usr/local/bin"
  else
    BASE_DIR="$HOME/.local"
    BIN_DIR="$HOME/.local/bin"
  fi
fi

mkdir -p "$BIN_DIR"
if [[ ! -w "$BIN_DIR" ]]; then
  fail "cannot write to $BIN_DIR (try sudo ./install.sh --system or --user)"
fi

APP_DIR="$BASE_DIR/share/terminal-dino"
mkdir -p "$APP_DIR"

log "installing python entry: $SOURCE_PY -> $BIN_DIR/dino"
install -m 0755 "$SOURCE_PY" "$BIN_DIR/dino"

install -m 0644 "$SOURCE_PY" "$APP_DIR/dino.py"
printf '#!/bin/sh\nexec "%s" "%s" "$@"\n' "$PYTHON_BIN" "$APP_DIR/dino.py" > "$BIN_DIR/dino"
chmod 0755 "$BIN_DIR/dino"

# ---- optional desktop entry (Linux/BSD) ----
if [[ -d "$HOME/.local" ]]; then
  DESK_DIR="$HOME/.local/share/applications"
  mkdir -p "$DESK_DIR"
  cat > "$DESK_DIR/terminal-dino.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Terminal Dino
Comment=Chrome's offline dinosaur in your terminal
Exec=$BIN_DIR/dino
Terminal=true
Categories=Game;
EOF
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESK_DIR" >/dev/null 2>&1 || true
fi

# ---- PATH help for user installs ----
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
      if [[ -f "$rc" ]]; then
        if ! grep -qF "$BIN_DIR" "$rc"; then
          printf '\n# terminal-dino\nexport PATH="%s:$PATH"\n' "$BIN_DIR" >> "$rc"
          log "added $BIN_DIR to $rc (restart your shell)"
        fi
      fi
    done
    ;;
esac

# ---- smoke check ----
if ! command -v "$BIN_DIR/dino" >/dev/null 2>&1 && [[ ! -x "$BIN_DIR/dino" ]]; then
  fail "install step did not place dino executable"
fi

cat <<EOF

Terminal Dino is installed.

Run it from any directory with:
    dino

If your shell doesn't find it yet, either restart your shell or run:
    export PATH="$BIN_DIR:\$PATH"

EOF

# cleanup temp file if we downloaded
if [[ -n "${TMP_PY:-}" && -f "${TMP_PY}" ]]; then rm -f "$TMP_PY"; fi
EOF
chmod +x install.sh
echo ready