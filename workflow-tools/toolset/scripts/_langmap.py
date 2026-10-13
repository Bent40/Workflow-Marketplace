"""_langmap.py — the language-extraction table shared by the repo's mappers.

Two tools walk a tree and pull top-level symbols out of the same languages:

  compress-context.py   one-shot markdown map (a prompt payload, no store)
  wf-map.py             persistent queryable index (_workflow/map.json)

The regex family, the signature cap, and the source-extension tuples used to
live in BOTH — so a language-support fix landed in one mapper and silently
missed the other. They live here once. Import site (both callers stand in
scripts/, so plain `import _langmap` resolves):

    from _langmap import JS_SYMBOL_RULES, SIG_MAXLEN, md_heading_re

DELIBERATELY NOT SHARED — these are per-tool POLICY, not duplication:

  * The full exclusion set. Both mappers agree on the noise floor below, but
    compress-context additionally drops `.DS_Store` while wf-map drops build
    outputs / vendor trees and deliberately KEEPS `.claude`. This module
    exports the common BASE; each tool states its own additions next to its
    own walker. Changing what a mapper walks is a behavior change, not a
    cleanup.
  * Heading depth. compress-context indexes h1-h2, wf-map h1-h3 — hence the
    `md_heading_re(max_level)` factory rather than one shared constant.

ORDER IS LOAD-BEARING: the extension collections are TUPLES, not sets.
compress-context resolves an extensionless JS import by trying candidates in
extension order (`./lib/util` -> util.js, util.ts, util/index.js, ...), so a
set would make resolution — and therefore the emitted import graph —
dependent on iteration order. Keep them tuples.

The symbol patterns carry CAPTURE GROUPS for the extractor that wants names
(wf-map); a capture group does not change `.match()` truthiness, so the caller
that only asks "is this a symbol line?" (compress-context) is unaffected.
"""
from __future__ import annotations

import re

# The noise floor both mappers agree on. Each tool extends this with its own
# additions — see the module docstring.
BASE_EXCLUDES = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".idea",
})

# Max characters of a captured signature line.
SIG_MAXLEN = 100

PY_EXTS = (".py",)
JS_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
MD_EXTS = (".md", ".markdown")

# Top-level Python def/class. Group 1 is the bare name.
PY_SYMBOL_RE = re.compile(r"^(?:async\s+def|def|class)\s+(\w+)")

# JS/TS symbol forms, as (kind, pattern) with group 1 = name. APPROXIMATE by
# design — exactness for a real symbol table is `wf describe`'s job.
JS_SYMBOL_RULES = (
    ("func", re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)")),
    ("class", re.compile(r"^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)")),
    ("func", re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*"
                        r"(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>")),
    ("func", re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function")),
)

# import/require specifiers; group 1 = the specifier string.
JS_IMPORT_RES = (
    re.compile(r"""(?:from|import)\s+['"]([^'"]+)['"]"""),
    re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)"""),
)


def md_heading_re(max_level: int) -> re.Pattern[str]:
    """Markdown ATX heading matcher for levels 1..max_level.

    Group 1 is the hashes (depth), group 2 the heading text. Depth is per-tool
    policy, so each mapper builds its own from this one pattern shape."""
    if not 1 <= max_level <= 6:
        raise ValueError(f"md_heading_re: max_level must be 1..6, got {max_level}")
    return re.compile(rf"^(#{{1,{max_level}}})\s+(.*\S)\s*$")
