"""Architecture guards for the shell + pure module split.

Each category is a package (``bot/<shell>/``): the shell lives in
``__init__.py`` (thin orchestration + patch seams) and the pure modules
beside it take explicit arguments. Top-level ``bot/*.py`` helpers
(redeem, risk, verify_run, ...) follow the same rules.

- Pure/domain modules must never import ``bot.live_paper`` (direct,
  deferred/function-level, or circular). AST scan catches imports at any
  nesting level; a dynamic-import scan catches ``__import__`` /
  ``importlib.import_module`` with a live_paper target.
- Shells must stay thin and delegate to their pure modules. Line caps fail
  when business logic grows in the shell instead of the pure module.

Keep the suite green: caps below include headroom over the sizes measured
when the guards were added.
"""

import ast
import unittest
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent.parent

# Shell packages (thin orchestration + patch seams): bot/<name>/__init__.py.
# Everything else under bot/ (top-level helpers and pure package modules)
# is treated as a guarded module that must not couple to bot.live_paper.
SHELLS = {
    "api",
    "live_paper",
    "executor",
    "replay",
    "ws",
    "ab_test",
    "fill_audit",
    "runs",
    "api_views",
}

# Sizes at guard time (shell __init__.py line counts): api 1029, live_paper 1476, executor 160,
# replay 83, ws 186, ab_test 162, fill_audit 93, runs 94, api_views 40.
# Caps give ~10% headroom on the thick shells and generous room on the thin
# ones; growing past a cap means move logic to the pure module instead.
SHELL_CAPS = {
    "api": 1130,
    "live_paper": 1620,
    "executor": 210,
    "replay": 130,
    "ws": 250,
    "ab_test": 220,
    "fill_audit": 150,
    "runs": 150,
    "api_views": 80,
}

# Each shell must delegate to these pure modules (checked via imports).
SHELL_DELEGATION = {
    "api": ["api_core", "api_loop", "api_markets", "api_views"],
    "live_paper": ["live_orders", "live_quotes", "live_phases", "live_records"],
    "executor": ["exec_pricing", "exec_sizing", "exec_hydrogen", "exec_ladder", "exec_sim"],
    "replay": ["replay_consts", "replay_sizing", "replay_slices", "replay_sim",
               "replay_analysis", "replay_cli"],
    "ws": ["ws_models", "ws_feed", "ws_tape", "ws_quotes"],
    "ab_test": ["ab_consts", "ab_stats", "ab_load", "ab_dist", "ab_meta", "ab_report"],
    "fill_audit": ["fill_util", "fill_roles", "fill_realism", "fill_verify"],
    "runs": ["runs_paths", "runs_tape", "runs_workspace", "runs_query"],
    "api_views": ["views_common", "views_snapshot", "views_perf", "views_trades"],
}


def _imported_basenames(tree):
    """All module basenames referenced by static import statements."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod:
                found.add(mod.split(".")[-1])
            for alias in node.names:
                found.add(alias.name.split(".")[-1])
    return found


def _live_paper_import_violations(tree):
    """Import statements that pull in bot.live_paper, at any nesting level."""
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == "live_paper" or name == "bot.live_paper" or name.endswith(".live_paper"):
                    violations.append(f"L{node.lineno}: import {name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "live_paper" or mod == "bot.live_paper" or mod.endswith(".live_paper"):
                violations.append(f"L{node.lineno}: from {mod} import ...")
            elif mod in ("bot", "") or (node.level and not mod):
                for alias in node.names:
                    if alias.name == "live_paper":
                        violations.append(f"L{node.lineno}: from {'bot' if mod == 'bot' else 'relative'} import live_paper")
        elif isinstance(node, ast.Call):
            func = node.func
            is_dynamic_import = False
            if isinstance(func, ast.Name) and func.id == "__import__":
                is_dynamic_import = True
            elif isinstance(func, ast.Attribute) and func.attr == "import_module":
                is_dynamic_import = True
            if is_dynamic_import and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    if "live_paper" in first.value:
                        violations.append(f"L{node.lineno}: dynamic import({first.value!r})")
    return violations


def _shell_path(shell):
    """The shell file for a category: its package __init__."""
    return BOT_DIR / shell / "__init__.py"


def _guarded_modules():
    """Every bot module that is not a shell (pure + shared helpers)."""
    mods = []
    for path in sorted(BOT_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        if path.stem in SHELLS:
            continue
        mods.append(path)
    for pkg in sorted(BOT_DIR.iterdir()):
        if not pkg.is_dir() or pkg.name == "tests":
            continue
        if not (pkg / "__init__.py").exists():
            continue
        for path in sorted(pkg.glob("*.py")):
            if path.name in ("__init__.py", "__main__.py"):
                continue
            mods.append(path)
    return mods


class TestNoLivePaperCoupling(unittest.TestCase):
    def test_pure_modules_do_not_import_live_paper(self):
        failures = []
        for path in _guarded_modules():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as ex:
                failures.append(f"{path.name}: unparsable ({ex})")
                continue
            for v in _live_paper_import_violations(tree):
                failures.append(f"{path.name} {v}")
        self.assertEqual(
            failures, [],
            "Pure modules must not import bot.live_paper (direct, deferred, or circular). "
            "Move shared logic to a pure module and pass it in explicitly:\n" + "\n".join(failures),
        )

    def test_shells_do_not_import_each_other_via_live_paper(self):
        # Shells other than live_paper itself must not import it either;
        # cross-shell coupling goes through pure modules.
        failures = []
        for shell in sorted(SHELLS - {"live_paper"}):
            path = _shell_path(shell)
            if not path.exists():
                failures.append(f"{shell}.py missing")
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for v in _live_paper_import_violations(tree):
                failures.append(f"{shell}.py {v}")
        self.assertEqual(failures, [], "Shells must not import bot.live_paper:\n" + "\n".join(failures))


class TestShellsStayThin(unittest.TestCase):
    def test_shell_line_caps(self):
        over = []
        for shell, cap in sorted(SHELL_CAPS.items()):
            path = _shell_path(shell)
            if not path.exists():
                over.append(f"{shell}.py missing")
                continue
            with path.open(encoding="utf-8", errors="ignore") as f:
                lines = sum(1 for _ in f)
            if lines > cap:
                over.append(
                    f"{shell}.py has {lines} lines (cap {cap}): "
                    "move business logic to its pure module(s) instead of growing the shell"
                )
        self.assertEqual(over, [], "\n".join(over))

    def test_shells_delegate_to_pure_modules(self):
        missing = []
        for shell, expected in sorted(SHELL_DELEGATION.items()):
            path = _shell_path(shell)
            if not path.exists():
                missing.append(f"{shell}.py missing")
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported = _imported_basenames(tree)
            for pure in expected:
                if pure not in imported:
                    missing.append(f"{shell}.py no longer delegates to pure module {pure}")
        self.assertEqual(missing, [], "\n".join(missing))


if __name__ == "__main__":
    unittest.main()
