#!/usr/bin/env python3
"""find.py — search the workflow toolset for the skill that fits a task.

Stdlib only, offline, deterministic. Two catalog sources, in order:

  1. <skill>/catalog.json — written by `wf plugin build` into the published
     workflow-core / workflow-full plugins. Lists EVERY public skill across the
     marketplace with the plugin(s) that ship it, so a match can be a skill the
     user has not installed yet (the answer then names the plugin to install).
  2. Live scan of sibling skill dirs (<skills>/*/SKILL.md) — used inside the
     workflow repo itself, where every skill is present and no catalog is built.

Usage:
  find.py "<what you want to do>" [--limit N] [--json]
  find.py --list [--json]           every catalog entry

Exit 0 with matches, 1 with none (grep convention), 2 on a broken catalog.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
CATALOG = SKILL_DIR / "catalog.json"

# Words that carry no routing signal in either a query or a description.
STOP = set("""a an and are as at be by can do for from have help how i in into is it its
me my need of on or our please run say says so that the their them then this to up use
used user wants when where which with you your want make get let""".split())


def _tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9+#.-]*", text.lower()):
        w = w.strip(".-")
        if len(w) < 2 or w in STOP:
            continue
        # light stemming so "tests"/"testing" meet "test"
        for suf in ("ing", "es", "s"):
            if len(w) > 4 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.append(w)
    return out


def _frontmatter(md: str) -> dict:
    """Tolerant name/description reader (no PyYAML on plugin machines)."""
    m = re.match(r"^---\s*\n(.*?)\n---", md, re.S)
    if not m:
        return {}
    fm: dict = {}
    for key in ("name", "description"):
        km = re.search(rf"^{key}:\s*(.*)$", m.group(1), re.M)
        if not km:
            continue
        val = km.group(1).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            q = val[0]
            val = val[1:-1].replace(q * 2, q) if q == "'" else val[1:-1]
        fm[key] = val
    return fm


def load_entries() -> tuple[list[dict], str]:
    if CATALOG.is_file():
        try:
            data = json.loads(CATALOG.read_text(encoding="utf-8"))
            entries = data["skills"]
            assert isinstance(entries, list)
        except Exception as e:  # fail loud, never search a half-read catalog
            print(f"find.py: catalog unreadable ({CATALOG}): {e}", file=sys.stderr)
            sys.exit(2)
        return entries, f"catalog ({data.get('marketplace', 'workflow')})"
    entries = []
    for md in sorted(SKILL_DIR.parent.glob("*/SKILL.md")):
        fm = _frontmatter(md.read_text(encoding="utf-8", errors="replace"))
        if fm.get("description"):
            entries.append({"id": fm.get("name") or md.parent.name,
                            "description": fm["description"], "plugins": []})
    return entries, f"live scan of {SKILL_DIR.parent}"


def rarity_table(entries: list[dict]) -> dict[str, float]:
    """Rare words route harder: "playwright" outweighs "test" across 140 skills."""
    df: dict[str, int] = {}
    for e in entries:
        for t in set(_tokens(e["id"].replace("-", " ") + " " + e["description"])):
            df[t] = df.get(t, 0) + 1
    n = max(len(entries), 1)
    return {t: 1 + math.log(n / c) for t, c in df.items()}


def score(entry: dict, q: list[str], raw_q: str, rarity: dict[str, float]) -> float:
    name = entry["id"].lower()
    name_t = set(_tokens(name.replace("-", " ")))
    desc = entry["description"]
    # Only the positive part of a description routes: text after "Distinct from"
    # / "Does NOT fire" / "NOT for" names OTHER skills and must not attract.
    pos = re.split(r"\b(?:distinct from|does not fire|not for|NOT for)\b", desc, maxsplit=1, flags=re.I)[0]
    desc_t = _tokens(pos)
    quoted = " ".join(re.findall(r"[\"“']([^\"”']{3,80})[\"”']", pos)).lower()
    s = 0.0
    if raw_q.strip().lower() in (name, name.replace("-", " ")):
        s += 10
    for t in set(q):
        w = rarity.get(t, 1.0)
        if t in name_t:
            s += 2 * w
        elif any(t in n for n in name_t):
            s += w
        if t in desc_t:
            s += w * (1.5 if t in quoted else 1)
    if len(raw_q) > 6 and raw_q.lower() in quoted:
        s += 5  # the query is (part of) a documented trigger phrase
    return s


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    limit = 5
    if "--limit" in argv:
        i = argv.index("--limit")
        limit = int(argv[i + 1])
        del argv[i:i + 2]
    args = [a for a in argv if a not in ("--json", "--list")]
    entries, source = load_entries()

    if "--list" in argv:
        hits = [(0.0, e) for e in sorted(entries, key=lambda e: e["id"])]
    else:
        raw = " ".join(args)
        q = _tokens(raw)
        if not q:
            print('usage: find.py "<what you want to do>" [--limit N] [--json] | --list', file=sys.stderr)
            return 2
        rarity = rarity_table(entries)
        hits = sorted(((score(e, q, raw, rarity), e) for e in entries), key=lambda h: (-h[0], h[1]["id"]))
        hits = [h for h in hits if h[0] >= 3][:limit]

    if as_json:
        print(json.dumps({"source": source,
                          "matches": [dict(e, score=round(s, 2)) for s, e in hits]}, indent=2))
        return 0 if hits else 1
    if not hits:
        print(f"no match ({len(entries)} skills searched, {source}) — the toolset likely has nothing for this; proceed without it")
        return 1
    print(f"{len(hits)} match(es) from {len(entries)} skills ({source}):")
    for s, e in hits:
        plug = e.get("plugins") or []
        where = f"  [plugin: {plug[0]}]" if plug else ""
        desc = e["description"]
        print(f"- {e['id']}{where}\n    {desc[:240]}{'…' if len(desc) > 240 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
