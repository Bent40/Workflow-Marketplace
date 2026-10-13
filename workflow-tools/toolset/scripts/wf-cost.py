#!/usr/bin/env python3
"""wf-cost.py — a local, read-only cost/usage readout parsed from Claude Code
transcripts (inspired by ccusage). Turns "cost is a quality axis" from a principle
into an instrument: it shows where tokens go (per model, split input / output /
cache-creation / cache-read so prompt-cache ROI is visible), buckets usage into
Anthropic's 5-hour rate-limit blocks, and projects a burn rate so the autonomy
boundary gets a "you'll run out before this finishes" early warning instead of
discovering the cap mid-task.

HONESTY / SAFETY:
  * READ-ONLY and LOCAL — it only reads ~/.claude/projects/**/*.jsonl (override
    with --dir); no network, nothing written. Nothing leaves the machine.
  * Tokens are the PRIMARY, always-honest readout. A dollar estimate is OPT-IN
    (--usd) and clearly APPROXIMATE — it uses an editable PRICES table that may be
    stale; never treat it as a bill.
  * FAILS OPEN: an unreadable file or a malformed/za schema-drifted line is SKIPPED,
    never a crash — a partial readout beats a hard error. If nothing parses it says
    "no usage found", not a fake zero-cost claim.

The work is done on plain records through a testable seam (`parse_root`,
`aggregate`, `session_blocks`, `burn_rate`), so --selftest injects synthetic
transcripts in a tempdir and never touches the real ~/.claude.

Usage:
    wf cost [--dir <root>] [--window-min N] [--usd] [--json]
    wf cost --selftest
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_ROOT = Path.home() / ".claude" / "projects"
BLOCK_HOURS = 5            # Anthropic's rolling rate-limit window
BURN_WINDOW_MIN = 60       # default look-back for the burn-rate

# Approximate per-Mtok USD prices, EDITABLE and possibly STALE. Keyed by a
# substring of the model id; first match wins. Used ONLY for the opt-in --usd
# estimate (input, output, cache-write, cache-read). Tokens are the source of
# truth; this is a convenience, never a bill.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "opus": (5.0, 25.0, 6.25, 0.50),
    "sonnet": (3.0, 15.0, 3.75, 0.30),
    "haiku": (0.80, 4.0, 1.0, 0.08),
}

TOKEN_FIELDS = ("input", "output", "cache_create", "cache_read")


def _die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    sys.stderr.write(f"wf cost: {msg}\n")
    raise SystemExit(code)


def _parse_ts(val) -> datetime | None:
    if not isinstance(val, str) or not val.strip():
        return None
    s = val.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def extract_usage(obj: dict) -> dict | None:
    """Pull a usage record from one transcript line, robust to schema variation.
    Returns {ts, model, input, output, cache_create, cache_read} or None if the
    line carries no usage (fail-open: never raises on a weird shape)."""
    if not isinstance(obj, dict):
        return None
    msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
    usage = obj.get("usage") or msg.get("usage")
    if not isinstance(usage, dict):
        return None

    def _int(*keys) -> int:
        for k in keys:
            v = usage.get(k)
            if isinstance(v, bool):
                continue
            if isinstance(v, int):
                return v
            if isinstance(v, float):
                return int(v)
        return 0

    rec = {
        "ts": _parse_ts(obj.get("timestamp") or msg.get("timestamp")),
        "model": str(obj.get("model") or msg.get("model") or "unknown"),
        "input": _int("input_tokens"),
        "output": _int("output_tokens"),
        "cache_create": _int("cache_creation_input_tokens", "cache_creation_tokens"),
        "cache_read": _int("cache_read_input_tokens", "cache_read_tokens"),
    }
    if all(rec[f] == 0 for f in TOKEN_FIELDS):
        return None  # a usage block with no tokens carries no signal
    return rec


def parse_root(root: Path) -> list[dict]:
    """Read every *.jsonl under `root`, extracting usage records. Fail-open per
    line and per file — a malformed line or unreadable file is skipped, never
    fatal."""
    records: list[dict] = []
    if not root.is_dir():
        return records
    for path in sorted(root.rglob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for raw in text.splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue  # schema drift / partial write — skip, don't crash
            rec = extract_usage(obj)
            if rec is not None:
                records.append(rec)
    return records


def _total(rec: dict) -> int:
    return sum(rec[f] for f in TOKEN_FIELDS)


def aggregate(records: list[dict]) -> dict:
    """Per-model and grand totals, plus the cache-hit ratio (cache_read over all
    input-side tokens) — the number that makes prompt-cache ROI visible."""
    by_model: dict[str, dict] = {}
    for r in records:
        m = by_model.setdefault(r["model"], {f: 0 for f in TOKEN_FIELDS})
        for f in TOKEN_FIELDS:
            m[f] += r[f]
    grand = {f: sum(m[f] for m in by_model.values()) for f in TOKEN_FIELDS}

    def _cache_hit(d: dict) -> float:
        seen = d["cache_read"] + d["input"]  # all input-side tokens
        return (d["cache_read"] / seen) if seen else 0.0

    return {
        "by_model": by_model,
        "grand": grand,
        "cache_hit": _cache_hit(grand),
        "n_records": len(records),
    }


def session_blocks(records: list[dict]) -> list[dict]:
    """Group timed records into rolling 5-hour blocks (ccusage's session-block
    model): a block opens at its first activity and spans BLOCK_HOURS; activity at
    or after a block's end opens a new block. Records with no timestamp are
    excluded from block accounting (counted in totals)."""
    timed = sorted((r for r in records if r["ts"]), key=lambda r: r["ts"])
    blocks: list[dict] = []
    cur: dict | None = None
    for r in timed:
        if cur is None or r["ts"] >= cur["end"]:
            cur = {"start": r["ts"], "end": r["ts"] + timedelta(hours=BLOCK_HOURS),
                   "tokens": 0, "n": 0}
            blocks.append(cur)
        cur["tokens"] += _total(r)
        cur["n"] += 1
    return blocks


def burn_rate(records: list[dict], now: datetime,
              window_min: int = BURN_WINDOW_MIN) -> dict:
    """Tokens/min over the last `window_min` minutes — the live consumption rate
    that powers an early 'you'll run out before this finishes' warning."""
    cutoff = now - timedelta(minutes=window_min)
    recent = [r for r in records if r["ts"] and r["ts"] >= cutoff]
    toks = sum(_total(r) for r in recent)
    return {"window_min": window_min, "tokens": toks, "n": len(recent),
            "per_min": (toks / window_min) if window_min else 0.0}


def _usd(by_model: dict) -> float | None:
    """Approximate USD across models from the editable PRICES table. Returns None
    if no model matched a price (so the caller can stay honest about coverage)."""
    total = 0.0
    matched = False
    for model, d in by_model.items():
        low = model.lower()
        price = next((p for key, p in PRICES.items() if key in low), None)
        if price is None:
            continue
        matched = True
        pin, pout, pcw, pcr = price
        total += (d["input"] * pin + d["output"] * pout
                  + d["cache_create"] * pcw + d["cache_read"] * pcr) / 1_000_000
    return total if matched else None


def _fmt(n: int) -> str:
    return f"{n:,}"


def render(records: list[dict], *, now: datetime, window_min: int,
           show_usd: bool) -> str:
    agg = aggregate(records)
    blocks = session_blocks(records)
    burn = burn_rate(records, now, window_min)
    out: list[str] = []
    out.append("── wf cost — local usage readout (read-only) ──────────────────")
    if not records:
        out.append("no usage found (no parseable transcripts under the search root).")
        out.append("───────────────────────────────────────────────────────────────")
        return "\n".join(out)
    out.append(f"records: {agg['n_records']}   models: {len(agg['by_model'])}")
    out.append("")
    out.append("Per model (tokens):")
    out.append(f"  {'model':<28} {'input':>12} {'output':>12} {'cache-wr':>12} {'cache-rd':>12}")
    for model in sorted(agg["by_model"]):
        d = agg["by_model"][model]
        name = model if len(model) <= 28 else model[:25] + "..."
        out.append(f"  {name:<28} {_fmt(d['input']):>12} {_fmt(d['output']):>12} "
                   f"{_fmt(d['cache_create']):>12} {_fmt(d['cache_read']):>12}")
    g = agg["grand"]
    out.append(f"  {'TOTAL':<28} {_fmt(g['input']):>12} {_fmt(g['output']):>12} "
               f"{_fmt(g['cache_create']):>12} {_fmt(g['cache_read']):>12}")
    out.append("")
    out.append(f"cache hit ratio: {agg['cache_hit']*100:.1f}%  "
               f"(cache-read / all input-side tokens — higher = better prompt-cache ROI)")
    out.append("")
    # Current (most recent) 5-hour block.
    if blocks:
        b = blocks[-1]
        elapsed_min = max(1.0, (now - b["start"]).total_seconds() / 60.0)
        proj = b["tokens"] / elapsed_min * (BLOCK_HOURS * 60)
        out.append(f"current 5h block: {_fmt(b['tokens'])} tokens in {b['n']} call(s); "
                   f"started {b['start'].strftime('%Y-%m-%dT%H:%MZ')}")
        out.append(f"  projected to block end (at this pace): ~{_fmt(int(proj))} tokens")
    out.append(f"burn rate (last {burn['window_min']}m): {burn['per_min']:.0f} tokens/min "
               f"({_fmt(burn['tokens'])} tokens in {burn['n']} call(s))")
    if show_usd:
        usd = _usd(agg["by_model"])
        if usd is None:
            out.append("approx cost: (no model matched the PRICES table — tokens only)")
        else:
            out.append(f"approx cost: ~${usd:.2f} USD  "
                       f"[APPROXIMATE — editable PRICES table, may be stale; not a bill]")
    out.append("───────────────────────────────────────────────────────────────")
    return "\n".join(out)


# --- selftest -----------------------------------------------------------------
def selftest() -> int:
    import tempfile
    problems: list[str] = []
    NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    def line(ts, model, i, o, cw, cr) -> str:
        return json.dumps({"type": "assistant", "timestamp": ts,
                           "message": {"model": model,
                                       "usage": {"input_tokens": i, "output_tokens": o,
                                                 "cache_creation_input_tokens": cw,
                                                 "cache_read_input_tokens": cr}}})

    with tempfile.TemporaryDirectory() as dd:
        root = Path(dd)
        proj = root / "proj-a"
        proj.mkdir()
        f = proj / "session.jsonl"
        f.write_text("\n".join([
            line("2026-01-01T11:30:00Z", "claude-opus-4-8", 1000, 200, 500, 4000),
            line("2026-01-01T11:45:00Z", "claude-opus-4-8", 100, 50, 0, 1500),
            line("2026-01-01T03:00:00Z", "claude-haiku-4-5", 800, 400, 0, 0),
            # a malformed line (fail-open: skipped) + a no-usage line (skipped)
            "{ this is not json",
            json.dumps({"type": "user", "message": {"content": "hi"}}),
        ]) + "\n")

        records = parse_root(root)
        # 3 usage records parse; 2 junk lines skipped (fail-open).
        if len(records) != 3:
            problems.append(f"parse_root: expected 3 usage records, got {len(records)}")

        agg = aggregate(records)
        opus = agg["by_model"].get("claude-opus-4-8", {})
        if opus.get("input") != 1100 or opus.get("cache_read") != 5500:
            problems.append(f"aggregate: opus totals wrong: {opus}")
        if agg["grand"]["output"] != 650:
            problems.append(f"aggregate: grand output wrong: {agg['grand']}")
        # cache hit = cache_read / (cache_read + input) = 5500 / (5500+1900) = 0.743..
        if not (0.74 <= agg["cache_hit"] <= 0.75):
            problems.append(f"aggregate: cache-hit ratio wrong: {agg['cache_hit']}")

        # blocks: the 03:00 haiku record is >5h before the 11:30 ones -> 2 blocks.
        blocks = session_blocks(records)
        if len(blocks) != 2:
            problems.append(f"session_blocks: expected 2 blocks, got {len(blocks)}")
        if blocks and blocks[-1]["tokens"] != 1000 + 200 + 500 + 4000 + 100 + 50 + 1500:
            problems.append(f"session_blocks: latest block tokens wrong: {blocks[-1]}")

        # burn rate over the last 60m from NOW(12:00): only the 11:30 + 11:45
        # records are within the window (09:00 is excluded).
        burn = burn_rate(records, NOW, 60)
        if burn["n"] != 2:
            problems.append(f"burn_rate: expected 2 recent records, got {burn['n']}")
        expected_burn_tokens = 1000 + 200 + 500 + 4000 + 100 + 50 + 0 + 1500
        if burn["tokens"] != expected_burn_tokens:
            problems.append(f"burn_rate: token sum wrong: {burn['tokens']}")

        # USD layer: opus + haiku both priced -> a positive estimate.
        usd = _usd(agg["by_model"])
        if usd is None or usd <= 0:
            problems.append(f"_usd: expected a positive estimate, got {usd}")
        # an unknown model yields None (honest about coverage).
        if _usd({"some-unknown-model": {f: 1 for f in TOKEN_FIELDS}}) is not None:
            problems.append("_usd: unknown model should yield None, not a fabricated price")

        # render is well-formed and fail-open on an empty root.
        rep = render(records, now=NOW, window_min=60, show_usd=True)
        if "cache hit ratio" not in rep or "burn rate" not in rep:
            problems.append("render: missing expected sections")
        empty = render([], now=NOW, window_min=60, show_usd=False)
        if "no usage found" not in empty:
            problems.append("render: empty input did not fail open with 'no usage found'")

    if problems:
        print("wf cost selftest: FAIL — " + "; ".join(problems))
        return 1
    print("wf cost selftest: PASS (parses transcripts fail-open over malformed/no-usage "
          "lines; per-model input/output/cache split + cache-hit ratio; 5h session "
          "blocks; burn-rate window; opt-in USD priced only for known models (unknown "
          "-> None, never fabricated); render fails open on empty)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="wf cost",
        description="Local, read-only cost/usage readout from Claude Code transcripts.")
    ap.add_argument("--dir", default=None,
                    help="transcripts root (default: ~/.claude/projects)")
    ap.add_argument("--window-min", type=int, default=BURN_WINDOW_MIN,
                    help=f"burn-rate look-back in minutes (default {BURN_WINDOW_MIN})")
    ap.add_argument("--usd", action="store_true",
                    help="also show an APPROXIMATE USD estimate (editable PRICES table)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a report")
    ap.add_argument("--selftest", action="store_true", help="run the selftest")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.window_min < 1:
        _die("--window-min must be >= 1")

    root = Path(args.dir) if args.dir else DEFAULT_ROOT
    now = datetime.now(timezone.utc)
    records = parse_root(root)
    if args.json:
        agg = aggregate(records)
        blocks = session_blocks(records)
        burn = burn_rate(records, now, args.window_min)
        payload = {
            "root": str(root), "n_records": agg["n_records"],
            "by_model": agg["by_model"], "grand": agg["grand"],
            "cache_hit": agg["cache_hit"],
            "blocks": [{"start": b["start"].isoformat(), "tokens": b["tokens"], "n": b["n"]}
                       for b in blocks],
            "burn": burn,
        }
        if args.usd:
            payload["approx_usd"] = _usd(agg["by_model"])
        print(json.dumps(payload, default=str, indent=2))
        return 0
    print(render(records, now=now, window_min=args.window_min, show_usd=args.usd))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
