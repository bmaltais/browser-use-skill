#!/usr/bin/env python3
"""
browser-use recipe system — store and replay DOM access patterns.

Recipes are JSON files in ./recipes/<name>.json that describe a sequence
of browser-use commands. On first run, you discover the right selectors;
on repeat runs, the recipe executes them directly — no screenshot needed.

If a step fails, the recipe:
  1. Tries fallback_selectors (for eval steps) silently
  2. Takes a screenshot and marks the step broken if all fallbacks fail
  3. Saves the updated recipe to disk for repair

Usage:
  recipe.py run <name> [--connect] [--profile NAME] [--headed] [--session NAME]
  recipe.py save <name> --file <path>
  recipe.py list
  recipe.py show <name>
  recipe.py delete <name>
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).parent
BU_SH = SKILL_DIR / "bu.sh"
RECIPES_DIR = SKILL_DIR / "recipes"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _auth_flags(auth: dict) -> list[str]:
    """Convert recipe auth block to bu.sh flag list."""
    mode = auth.get("mode", "headless")
    flags = []
    if mode == "connect":
        flags.append("--connect")
    elif mode == "profile":
        profile = auth.get("profile") or "Default"
        flags.extend(["--profile", profile])
    if auth.get("headed"):
        flags.append("--headed")
    session = auth.get("session", "default")
    if session != "default":
        flags.extend(["--session", session])
    return flags


# ---------------------------------------------------------------------------
# Core subprocess shim
# ---------------------------------------------------------------------------

def _bu(*args, auth_flags: list[str] = (), timeout: int = 30) -> tuple[str, int]:
    """Run a bu.sh command and return (stdout, returncode).

    Uses 'bash' which must be in PATH (standard on Linux/macOS; provided by
    Git Bash or WSL on Windows). BU_SH is passed as a POSIX path so Git Bash
    on Windows translates it correctly.
    """
    cmd = ["bash", BU_SH.as_posix(), *auth_flags, *[str(a) for a in args]]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip(), result.returncode


def _parse_eval_result(raw: str) -> str | None:
    """Extract value from `result: <value>` output of bu eval."""
    for line in raw.splitlines():
        if line.startswith("result:"):
            return line[len("result:"):].strip()
    # Fallback: return the whole output if no prefix found
    return raw if raw else None


# ---------------------------------------------------------------------------
# Step execution
# ---------------------------------------------------------------------------

def _run_step(step: dict, ctx: dict, auth_flags: list[str]) -> tuple[bool, str | None]:
    """
    Execute one recipe step.
    Returns (ok, output_value).
    Writes to ctx[step["output_var"]] on success if output_var is set.
    """
    step_type = step.get("type", "eval")
    out_var = step.get("output_var")

    if step_type == "navigate":
        url = step["url"].format_map(ctx)
        out, code = _bu("open", url, auth_flags=auth_flags, timeout=60)
        if code != 0:
            return False, out
        wait_for = step.get("wait_for")
        if wait_for:
            wait_args = ["wait", "selector", wait_for]
            timeout_ms = step.get("wait_timeout_ms", 10000)
            wait_args += ["--timeout", str(timeout_ms)]
            out, code = _bu(*wait_args, auth_flags=auth_flags, timeout=30)
            if code != 0:
                return False, f"wait_for timeout: {wait_for}"
        return True, None

    elif step_type == "wait":
        selector = step.get("selector")
        text = step.get("text")
        timeout_ms = step.get("timeout_ms", 10000)
        if selector:
            state = step.get("wait_state", "attached")
            out, code = _bu(
                "wait", "selector", selector,
                "--state", state, "--timeout", str(timeout_ms),
                auth_flags=auth_flags, timeout=30,
            )
        elif text:
            out, code = _bu(
                "wait", "text", text, "--timeout", str(timeout_ms),
                auth_flags=auth_flags, timeout=30,
            )
        else:
            return False, "wait step requires 'selector' or 'text'"
        return code == 0, out if code != 0 else None

    elif step_type == "eval":
        js = step["js"].format_map(ctx)
        out, code = _bu("eval", js, auth_flags=auth_flags)
        if code == 0:
            value = _parse_eval_result(out)
            if out_var is not None:
                ctx[out_var] = value
            return True, value

        # Primary JS failed — try fallback_selectors
        for selector in step.get("fallback_selectors", []):
            fallback_js = f"document.querySelector('{selector}')?.innerText ?? ''"
            out, code = _bu("eval", fallback_js, auth_flags=auth_flags)
            if code == 0:
                value = _parse_eval_result(out)
                if value:
                    print(f"  [recipe] fallback selector matched: {selector}", file=sys.stderr)
                    if out_var is not None:
                        ctx[out_var] = value
                    return True, value

        return False, f"eval failed and all fallbacks exhausted for step '{step.get('id', '?')}'"

    elif step_type == "click":
        index = step["index"]
        out, code = _bu("click", str(index), auth_flags=auth_flags)
        return code == 0, out if code != 0 else None

    elif step_type == "input":
        index = step["index"]
        value = step.get("text", "").format_map(ctx)
        out, code = _bu("input", str(index), value, auth_flags=auth_flags)
        return code == 0, out if code != 0 else None

    elif step_type == "scroll":
        direction = step.get("direction", "down")
        amount = step.get("amount")
        args = ["scroll", direction]
        if amount:
            args += ["--amount", str(amount)]
        out, code = _bu(*args, auth_flags=auth_flags)
        return code == 0, None

    else:
        return False, f"unknown step type: {step_type!r}"


# ---------------------------------------------------------------------------
# Recipe operations
# ---------------------------------------------------------------------------

def run_recipe(name: str, auth_override: dict | None = None) -> int:
    """Execute a recipe. Returns exit code."""
    recipe_path = RECIPES_DIR / f"{name}.json"
    if not recipe_path.exists():
        print(f"Recipe '{name}' not found in {RECIPES_DIR}", file=sys.stderr)
        print(f"Available: {[p.stem for p in RECIPES_DIR.glob('*.json')]}", file=sys.stderr)
        return 1

    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    # Merge: recipe auth is the base; auth_override (from CLI) wins per-key
    auth = {**recipe.get("auth", {}), **(auth_override or {})}
    auth_flags = _auth_flags(auth)

    ctx: dict = {}
    broken = False

    # Navigate to recipe URL first (unless first step is already a navigate)
    if not recipe["steps"] or recipe["steps"][0].get("type") != "navigate":
        out, code = _bu("open", recipe["url"], auth_flags=auth_flags, timeout=60)
        if code != 0:
            print(f"[recipe] failed to open {recipe['url']}: {out}", file=sys.stderr)
            return 1

    for step in recipe["steps"]:
        step_id = step.get("id", "?")
        ok, output = _run_step(step, ctx, auth_flags)

        if not ok:
            broken = True
            print(f"[recipe] step '{step_id}' FAILED: {output}", file=sys.stderr)
            # Save screenshot for diagnosis
            screenshot_path = SKILL_DIR / f"recipes/.broken_{name}_{step_id}.png"
            _bu("screenshot", str(screenshot_path), auth_flags=auth_flags)
            print(f"[recipe] screenshot saved: {screenshot_path}", file=sys.stderr)
            print(f"[recipe] update step '{step_id}' in {recipe_path}", file=sys.stderr)
            # Update metadata
            recipe.setdefault("metadata", {})["broken_step"] = step_id
            recipe["metadata"]["last_run_status"] = "broken"
            recipe_path.write_text(json.dumps(recipe, indent=2), encoding="utf-8")
            return 1

    # All steps passed — print output
    output_cfg = recipe.get("output", {})
    out_var = output_cfg.get("var")
    if out_var and out_var in ctx:
        print(ctx[out_var])
    elif ctx:
        # Print last written context value
        print(list(ctx.values())[-1])

    # Update metadata
    recipe.setdefault("metadata", {})
    recipe["metadata"]["last_run"] = datetime.now().isoformat()[:10]
    recipe["metadata"]["last_run_status"] = "ok"
    recipe["metadata"]["run_count"] = recipe["metadata"].get("run_count", 0) + 1
    recipe["metadata"]["broken_step"] = None
    recipe_path.write_text(json.dumps(recipe, indent=2), encoding="utf-8")
    return 0


def save_recipe(name: str, file_path: str) -> int:
    """Install a recipe JSON file into the recipes directory."""
    src = Path(file_path)
    if not src.exists():
        print(f"File not found: {file_path}", file=sys.stderr)
        return 1

    recipe = json.loads(src.read_text(encoding="utf-8"))
    recipe["name"] = name  # ensure name matches filename

    RECIPES_DIR.mkdir(exist_ok=True)
    dest = RECIPES_DIR / f"{name}.json"
    dest.write_text(json.dumps(recipe, indent=2), encoding="utf-8")
    print(f"Recipe '{name}' saved to {dest}")
    return 0


def list_recipes() -> int:
    """List all installed recipes."""
    RECIPES_DIR.mkdir(exist_ok=True)
    recipes = sorted(RECIPES_DIR.glob("*.json"))
    if not recipes:
        print("No recipes stored. Add one with: bu recipe save <name> --file <json>")
        return 0
    print(f"{'Name':<25} {'URL':<45} {'Last Run':<12} {'Status':<8} {'Runs'}")
    print("-" * 100)
    for p in recipes:
        if p.name.startswith("."):
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        meta = r.get("metadata", {})
        print(
            f"{r.get('name','?'):<25} "
            f"{r.get('url','?')[:43]:<45} "
            f"{(meta.get('last_run') or 'never'):<12} "
            f"{(meta.get('last_run_status') or '—'):<8} "
            f"{meta.get('run_count',0)}"
        )
    return 0


def show_recipe(name: str) -> int:
    """Pretty-print a recipe's JSON."""
    recipe_path = RECIPES_DIR / f"{name}.json"
    if not recipe_path.exists():
        print(f"Recipe '{name}' not found.", file=sys.stderr)
        return 1
    print(recipe_path.read_text(encoding="utf-8"))
    return 0


def delete_recipe(name: str) -> int:
    """Remove a recipe."""
    recipe_path = RECIPES_DIR / f"{name}.json"
    if not recipe_path.exists():
        print(f"Recipe '{name}' not found.", file=sys.stderr)
        return 1
    recipe_path.unlink()
    print(f"Recipe '{name}' deleted.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="browser-use recipe system — store and replay DOM access patterns",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # run
    p_run = sub.add_parser("run", help="Execute a recipe by name")
    p_run.add_argument("name", help="Recipe name (without .json)")
    p_run.add_argument("--connect", action="store_true", help="Override auth: use CDP connect")
    p_run.add_argument("--profile", metavar="NAME", help="Override auth: use Chrome profile")
    p_run.add_argument("--headed", action="store_true", help="Show browser window")
    p_run.add_argument("--session", default=None, help="Named browser session")

    # save
    p_save = sub.add_parser("save", help="Install a recipe JSON file")
    p_save.add_argument("name", help="Recipe name to use")
    p_save.add_argument("--file", required=True, metavar="PATH", help="Path to recipe JSON")

    # list
    sub.add_parser("list", help="List installed recipes")

    # show
    p_show = sub.add_parser("show", help="Print a recipe's full JSON")
    p_show.add_argument("name")

    # delete
    p_del = sub.add_parser("delete", help="Delete a recipe")
    p_del.add_argument("name")

    args = parser.parse_args()

    if args.cmd == "run":
        override = {}
        if args.connect:
            override["mode"] = "connect"
        elif args.profile:
            override["mode"] = "profile"
            override["profile"] = args.profile
        if args.headed:
            override["headed"] = True
        if args.session:
            override["session"] = args.session
        sys.exit(run_recipe(args.name, override or None))

    elif args.cmd == "save":
        sys.exit(save_recipe(args.name, args.file))

    elif args.cmd == "list":
        sys.exit(list_recipes())

    elif args.cmd == "show":
        sys.exit(show_recipe(args.name))

    elif args.cmd == "delete":
        sys.exit(delete_recipe(args.name))


if __name__ == "__main__":
    main()
