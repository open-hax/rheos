#!/usr/bin/env bash
set -euo pipefail

# Bootstrap source dependencies that are not available as npm source packages.
# This is a TEMPORARY declared Git dependency — not an undeclared ambient sibling checkout.
#
# Protocols: stays in eta-mu (not extracted), fetched from donor SHA.
# Chat UI: extracted to open-hax/chat-ui, fetched from new repo SHA.

ETA_MU_SHA="0ed56aa74a53a1d1e9c2e55ce95451817a7f3a90"
CHAT_UI_SHA="86385532b4f8606946555d0ada8e3fb22f35b4c3"
ETA_MU_URL="https://github.com/open-hax/eta-mu.git"
CHAT_UI_URL="https://github.com/open-hax/chat-ui.git"
DEPS_DIR="$(cd "$(dirname "$0")/.." && pwd)/deps"

mkdir -p "$DEPS_DIR"

# Fetch Protocols from eta-mu donor (not extracted)
if [ ! -d "$DEPS_DIR/protocols/src" ] || [ "$(find "$DEPS_DIR/protocols/src" -type f | wc -l)" = "0" ]; then
  echo "Fetching Protocols source from eta-mu@$ETA_MU_SHA..."
  TMPDIR=$(mktemp -d)
  git clone --quiet "$ETA_MU_URL" "$TMPDIR" 2>/dev/null
  git -C "$TMPDIR" checkout "$ETA_MU_SHA" --quiet
  mkdir -p "$DEPS_DIR/protocols/src"
  cp -r "$TMPDIR/packages/protocols/src/"* "$DEPS_DIR/protocols/src/" 2>/dev/null || true
  rm -rf "$TMPDIR"
  echo "  protocols/src: $(find "$DEPS_DIR/protocols/src" -type f | wc -l) files"
fi

# Fetch Chat UI from new open-hax/chat-ui repo
if [ ! -d "$DEPS_DIR/chat-ui/src" ] || [ "$(find "$DEPS_DIR/chat-ui/src" -type f | wc -l)" = "0" ]; then
  echo "Fetching Chat UI source from open-hax/chat-ui@$CHAT_UI_SHA..."
  TMPDIR=$(mktemp -d)
  git clone --quiet "$CHAT_UI_URL" "$TMPDIR" 2>/dev/null
  git -C "$TMPDIR" checkout "$CHAT_UI_SHA" --quiet
  mkdir -p "$DEPS_DIR/chat-ui/src"
  cp -r "$TMPDIR/src/"* "$DEPS_DIR/chat-ui/src/" 2>/dev/null || true
  rm -rf "$TMPDIR"
  echo "  chat-ui/src: $(find "$DEPS_DIR/chat-ui/src" -type f | wc -l) files"
fi

echo "Source deps ready at $DEPS_DIR"
