#!/bin/bash
# browser-use skill wrapper
# Auto-bootstraps local venv on first run via uv, then delegates all args.
# Usage: bash ~/.claude/skills/browser-use/bu.sh [--connect] <command> [args...]
#        bash ~/.claude/skills/browser-use/bu.sh recipe <subcommand> [args...]

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONUTF8=1

# Intercept 'recipe' subcommand — route to recipe.py instead of browser-use CLI
if [ "$1" = "recipe" ]; then
  shift
  exec uv run --directory "$SKILL_DIR" python "$SKILL_DIR/recipe.py" "$@"
fi

exec uv run --directory "$SKILL_DIR" browser-use "$@"
