#!/usr/bin/env python3
"""Distill a SMALL design/UX SFT set from a teacher model (stdlib only) — for the proof run.

Hits the teacher (an Ollama-compatible ``/api/chat`` endpoint, e.g. a large local model on a
LAN box) for a handful of design/UX prompts and writes chat-format JSONL, so a small-GPU
fine-tune proof has real teacher data without a cross-repo artifact handoff. Honest:
short/empty answers are skipped; a fully empty result is a non-zero exit. This is the SMALL
pilot; a full seed corpus + dataset would live in a separate data repo.

Config via env:
  WF_TEACHER_URL    default http://localhost:11434
  WF_TEACHER_MODEL  default gpt-oss:120b
  WF_FT_DATA        output JSONL (default ~/.wf-finetune/data/design-ux.jsonl)
  WF_DISTILL_N      number of seeds to use (default 12)

Optional private overrides: if ``core/private/finetune.yaml`` exists next to this checkout,
its ``teacher_url`` / ``teacher_model`` / ``data`` keys replace the defaults above and its
``legacy_env_prefix`` key names an older env-var prefix still honoured as a fallback.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

_PRIVATE_CFG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "private", "finetune.yaml"
)


def _load_private_cfg() -> dict:
    """Flat ``key: value`` reader for the optional private config (stdlib only)."""
    cfg: dict = {}
    try:
        with open(_PRIVATE_CFG_PATH, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return cfg
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        cfg[key.strip()] = val.strip().strip('"').strip("'")
    return cfg


_CFG = _load_private_cfg()


def _env(name: str, default: str) -> str:
    """``name`` (a WF_* var) wins; else the private legacy-prefixed twin; else default."""
    if name in os.environ:
        return os.environ[name]
    legacy = _CFG.get("legacy_env_prefix", "")
    if legacy and name.startswith("WF_") and legacy + name[3:] in os.environ:
        return os.environ[legacy + name[3:]]
    return default


_URL = _env("WF_TEACHER_URL", _CFG.get("teacher_url", "http://localhost:11434"))
_MODEL = _env("WF_TEACHER_MODEL", _CFG.get("teacher_model", "gpt-oss:120b"))
_OUT = os.path.expanduser(_env("WF_FT_DATA", _CFG.get("data", "~/.wf-finetune/data/design-ux.jsonl")))
_N = int(_env("WF_DISTILL_N", "12"))

_SYSTEM = (
    "You are a senior product and UX designer. Answer the task with a concrete, well-structured "
    "design response: briefly state assumptions, then give the specific design (layout, components, "
    "hierarchy, states, copy) with short rationale. Be decisive. No preamble or meta-commentary."
)

_SEEDS = [
    "Design the empty state for a brand-new team chat workspace with no messages yet.",
    "Design a destructive-confirmation dialog for permanently deleting a project.",
    "Design the 'connection lost / reconnecting' experience for a real-time collaborative editor.",
    "Specify the states of a primary button: default, hover, focus, active, loading, disabled, success.",
    "Design an accessible status system (success/warning/error/info) that does not rely on color alone.",
    "Design a command palette (fuzzy launcher): input, result grouping, keyboard nav, actions vs navigation.",
    "Design the zero-results state for a search feature: copy, suggested next actions, query recovery.",
    "Design the 'unsaved changes' guard when a user navigates away from a half-finished form.",
    "Design a multi-step checkout that minimizes abandonment: step sequence, progress, editing earlier steps.",
    "Design a notification center: trigger badge, grouping, read/unread, mark-all-read, empty state.",
    "Design keyboard focus management for a modal: focus on open, the trap, and return on close.",
    "Design an undo pattern for a destructive action that avoids a confirmation dialog (toast + timer).",
    "Write the microcopy for three empty states (no items, no search results, no permission).",
    "Design a dark-mode variant of a design-token system: which tokens flip, which stay, elevation strategy.",
    "Design the confirmation moment before an AI executes a state-changing action it proposed.",
    "Design a settings screen with 40+ options: grouping, prioritization, and the navigation pattern.",
]


def _chat(task: str) -> str:
    payload = json.dumps(
        {
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": task},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.7, "num_predict": 1024},
        }
    ).encode()
    req = urllib.request.Request(
        f"{_URL.rstrip('/')}/api/chat", data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        body = json.loads(resp.read())
    return (body.get("message", {}) or {}).get("content", "") or ""


def main() -> int:
    os.makedirs(os.path.dirname(_OUT), exist_ok=True)
    print(f"=== distill_mini teacher={_MODEL} url={_URL} n={_N} -> {_OUT} ===")
    records = []
    for i, task in enumerate(_SEEDS[:_N]):
        try:
            ans = _chat(task).strip()
        except Exception as exc:  # noqa: BLE001
            print(f"  SKIP {i}: {type(exc).__name__}: {exc}")
            continue
        if len(ans) >= 80:
            records.append({"messages": [{"role": "user", "content": task}, {"role": "assistant", "content": ans}]})
            print(f"  ok {i}: {len(ans)} chars")
        else:
            print(f"  SKIP {i}: answer too short ({len(ans)} chars)")
    if not records:
        print("FATAL: 0 usable examples")
        return 1
    with open(_OUT, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"=== wrote {len(records)} records -> {_OUT} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
