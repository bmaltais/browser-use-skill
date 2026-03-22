# browser-use — Claude Code Skill

A [Claude Code](https://claude.ai/code) skill for browser automation. Wraps the [browser-use](https://github.com/browser-use/browser-use) library with a clean shell interface and adds a **recipe system** for storing and replaying DOM access patterns without repeated visual discovery.

## Platform Support

Works on **Linux**, **macOS**, and **Windows** (Git Bash or WSL required on Windows).

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) — Python package manager
- `bash` in PATH (standard on Linux/macOS; Git Bash or WSL on Windows)
- Python 3.11+

## Installation

```bash
# Clone into your Claude Code skills directory
git clone https://github.com/bmaltais/browser-use-skill ~/.claude/skills/browser-use

# First run auto-bootstraps the .venv (takes ~60s, downloads ~200MB)
bash ~/.claude/skills/browser-use/bu.sh open https://example.com
```

Then add to your `~/.claude/CLAUDE.md` or skills config so Claude Code picks it up.

## Quick Start

```bash
# Shorthand alias (optional — add to your shell profile)
alias bu='bash ~/.claude/skills/browser-use/bu.sh'

bu open https://example.com       # Headless Chromium
bu --headed open https://x.com    # Visible window
bu --connect open https://x.com   # Connect to running Chrome (CDP)
bu state                          # List clickable elements with indices
bu eval "document.title"          # Run JavaScript
bu close                          # Close session
```

## Recipe System

Recipes store DOM access patterns as JSON files. On first use you discover the right selectors; on repeat runs the recipe executes them directly — no screenshot, no element scanning.

```bash
bu recipe list                          # Show installed recipes + run history
bu recipe run x_notifications           # Execute without visual discovery
bu recipe run x_notifications --headed  # Debug with visible browser
bu recipe show x_notifications          # Print recipe JSON
bu recipe save myrecipe --file foo.json # Install a recipe
bu recipe delete myrecipe               # Remove a recipe
```

**Self-healing**: if a JS selector breaks, `fallback_selectors` are tried silently. If all fail, a diagnostic screenshot is saved and the broken step is flagged in the recipe JSON.

See [`recipes/x_notifications.json`](recipes/x_notifications.json) for a working example.

## Authentication Modes

| Mode | Command | Use case |
|------|---------|----------|
| Headless | `bu open <url>` | No login needed |
| CDP connect | `bu --connect open <url>` | Reuse running Chrome session |
| Chrome profile | `bu --profile "Default" open <url>` | Saved logins/cookies |

## Full Documentation

See [`SKILL.md`](SKILL.md) for the complete command reference including navigation, interactions, data extraction, cookies, Python bridge, cloud API, and tunneling.

## License

MIT
