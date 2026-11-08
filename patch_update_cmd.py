#!/usr/bin/env python3
"""Idempotently apply the local frontend-skip hack to hermes update.

Reproduces the diff between /root/update_cmd.py.unedit (pristine) and
/root/update_cmd.py.1 (patched). Both insertions are located by their
anchor strings, so the script survives small line shifts:

  1. A helper block right before `def _complete_source_update(...)`
     defining _remove_frontend_package_jsons(), which renames
     ui-tui/package.json and web/package.json to .bak after the git
     move but before the completion build phase, so that
     source_build.source_frontends() no longer finds them.

  2. One call line inside _complete_source_update(), after
     `from hermes_cli.update_completion import settle_lost_completion`
     and before `lost = False` / `try: result = run_completion(request)`.

Usage:
  python3 patch_update_cmd.py [target_path]
  # defaults to ~/.hermes/hermes-agent/hermes_cli/update_cmd.py
"""
import sys
import time
from pathlib import Path

TARGET = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else (
    Path.home() / ".hermes" / "hermes-agent" / "hermes_cli" / "update_cmd.py"
)

ANCHOR1 = "def _complete_source_update(request: dict | None) -> None:"

ANCHOR2 = "    from hermes_cli.update_completion import settle_lost_completion\n"

BLOCK1 = """# --- Local hack: skip ui-tui/web frontend builds during `hermes update` ---
# Why here: git move (merge --ff-only / checkout --detach / reset --hard) runs
# before the build phase and restores tracked package.json files from HEAD,
# so deleting them before the git phase is undone. Deleting here -- after the
# git move and stash restore, before run_completion() spawns the completion
# child that calls build_update_products() -- makes source_build.source_frontends()
# see them missing and skip Node deps / TUI / web UI. Covers both pulled and
# already-up-to-date paths (both end in _complete_source_update).
# Best-effort only: a failure must never abort an already-committed update.
_FRONTEND_PACKAGE_JSONS = ("ui-tui/package.json", "web/package.json")


def _remove_frontend_package_jsons(root=None) -> list[str]:
    \"\"\"Move frontend manifests aside (.bak) so update's build phase skips them.\"\"\"
    root = Path(root) if root is not None else _m().PROJECT_ROOT
    removed: list[str] = []
    for rel in _FRONTEND_PACKAGE_JSONS:
        try:
            src = root / rel
            if src.is_file():
                src.replace(root / f"{rel}.bak")
                removed.append(rel)
        except OSError as exc:  # health: allow BLE001 -- best-effort hack, never abort update
            print(f"  ⚠ local hack: could not remove {rel}: {exc}")
    if removed:
        print(f"  ⓘ local hack: removed frontend manifest(s) to skip Node/TUI/web build: "
              f"{', '.join(removed)}")
    return removed


"""

LINE2 = '    _remove_frontend_package_jsons(Path(request["source"]) if request.get("source") else None)\n'


def main() -> int:
    if not TARGET.is_file():
        raise SystemExit(f"target not found: {TARGET}")
    text = TARGET.read_text(encoding="utf-8")
    if "_remove_frontend_package_jsons" in text:
        print(f"already patched: {TARGET}")
        return 0
    if text.count(ANCHOR1) != 1:
        raise SystemExit(f"anchor1 count={text.count(ANCHOR1)} (expected 1): {ANCHOR1}")
    if text.count(ANCHOR2) != 1:
        raise SystemExit(f"anchor2 count={text.count(ANCHOR2)} (expected 1): {ANCHOR2!r}")
    # 1) insert helper block immediately before def _complete_source_update
    text = text.replace(ANCHOR1, BLOCK1 + ANCHOR1, 1)
    # 2) insert the call line right after the settle_lost_completion import
    text = text.replace(ANCHOR2, ANCHOR2 + LINE2, 1)

    backup = TARGET.with_name(TARGET.name + f".pre-hack-{time.strftime('%Y%m%d-%H%M%S')}.bak")
    backup.write_text(TARGET.read_text(encoding="utf-8"), encoding="utf-8")
    tmp = TARGET.with_suffix(".py.patch-tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(TARGET)  # atomic on same filesystem
    # verify the patched file still compiles
    import py_compile
    py_compile.compile(str(TARGET), doraise=True)
    print(f"patched: {TARGET}")
    print(f"backup:  {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
