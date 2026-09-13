#!/usr/bin/env bash
set -euo pipefail

# Bootstrap source dependencies that are not available as npm source packages.
# This is a TEMPORARY declared Git dependency — not an undeclared ambient sibling checkout.
# After E1.06, these will point to the new open-hax repos.

DONOR_SHA="0ed56aa74a53a1d1e9c2e55ce95451817a7f3a90"
DONOR_URL="https://github.com/open-hax/eta-mu.git"
DEPS_DIR="$(cd "$(dirname "$0")/.." && pwd)/deps"

mkdir -p "$DEPS_DIR"

if [ -d "$DEPS_DIR/.git" ]; then
  echo "Source deps already fetched at $DEPS_DIR"
  exit 0
fi

echo "Fetching source dependencies from donor $DONOR_SHA..."
git clone --depth 1 --branch main "$DONOR_URL" "$DEPS_DIR/.donor" 2>/dev/null || \
  git -C "$DEPS_DIR/.donor" fetch origin "$DONOR_SHA" 2>/dev/null

git -C "$DEPS_DIR/.donor" checkout "$DONOR_SHA" --quiet

# Extract only the source directories needed
mkdir -p "$DEPS_DIR/protocols/src" "$DEPS_DIR/chat-ui/src"
cp -r "$DEPS_DIR/.donor/packages/protocols/src/"* "$DEPS_DIR/protocols/src/" 2>/dev/null || true
cp -r "$DEps_DIR/.donor/packages/chat-ui/src/"* "$DEPS_DIR/chat-ui/src/" 2>/dev/null || true

# Clean up the full donor clone
rm -rf "$DEPS_DIR/.donor"

echo "Source deps staged at $DEPS_DIR"
echo "  - protocols/src: $(find "$DEPS_DIR/protocols/src" -type f | wc -l) files"
echo "  - chat-ui/src: $(find "$DEPS_DIR/chat-ui/src" -type f | wc -l) files"
