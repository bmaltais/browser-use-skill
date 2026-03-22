#!/usr/bin/env bash
# grok.sh — Submit a research query to X Grok and print the response
# Usage: bash ~/.claude/skills/browser-use/grok.sh "your question here"
#
# Requires Chrome running with --remote-debugging-port=9222 (CDP mode)

set -e

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BU="bash $SKILL_DIR/bu.sh --connect"
QUERY="${1:-What are the latest Claude Code best practices?}"

echo "[grok] Navigating to x.com/i/grok..."
$BU open "https://x.com/i/grok" > /dev/null

echo "[grok] Waiting for input..."
$BU wait selector "textarea[placeholder='Ask anything']" --timeout 8000 > /dev/null

# Get the textarea index
TEXTAREA_IDX=$($BU state 2>/dev/null | grep -oP '\[\d+\](?=<textarea.*placeholder=Ask anything)' | grep -oP '\d+' | head -1)

if [ -z "$TEXTAREA_IDX" ]; then
  echo "[grok] ERROR: Could not find Grok textarea" >&2
  exit 1
fi

echo "[grok] Typing query into element $TEXTAREA_IDX..."
$BU input "$TEXTAREA_IDX" "$QUERY" > /dev/null

# Find and click the Grok submit button by aria-label
echo "[grok] Submitting..."
$BU eval "
(function() {
  const btn = document.querySelector('[aria-label=\"Grok something\"]');
  if (!btn) return 'ERROR: submit button not found';
  btn.click();
  return 'submitted';
})()
" > /dev/null

echo "[grok] Waiting for response (up to 90s)..."
$BU wait text "Thought for" --timeout 90000 > /dev/null
sleep 5

echo "[grok] Extracting response..."
echo "---"
$BU eval "
(function() {
  const spans = Array.from(document.querySelectorAll('span, p, li, h2, h3'))
    .map(e => e.innerText.trim())
    .filter(t => t.length > 25);
  const start = spans.findIndex(t =>
    t.startsWith('Based on') || t.startsWith('Here are') ||
    t.startsWith('According') || t.length > 80
  );
  return spans.slice(start >= 0 ? start : 0, start + 150).join('\n');
})()
"
