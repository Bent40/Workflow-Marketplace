#!/usr/bin/env python3
"""wf-orchestra.py — model-agnostic measurement baseline harness.

The FIRST deliverable of the "specialist orchestra" build (see
docs/orchestra/specialist-orchestra.md §3): score a candidate SMALL model — *prompted* with
a skill's instructions — against that skill's own evals, to find which skills a
strong-enough 7-14B already passes versus which actually need fine-tuning. This
tells us the real fine-tuning workload BEFORE any GPU spend, and produces the
skill->specialist clustering signal. It reuses bmad's existing eval culture
(`evals.json` / `triggers.json`, the bmad-eval-runner grader rubric) rather than
inventing a new eval format.

    wf orchestra baseline --model <url> --model-name <name> [--quant <label>]
                             [--grader assertion|judge|hybrid] [--judge-model <url>]
                             [--judge-model-name <name>] [--skills <glob>]
                             [--limit N] [--threshold F] [--out <report.md>]
    wf orchestra --selftest

Per skill WITH evals:
  1. Build chat messages = [system: the skill's SKILL.md instructions (trimmed),
     user: the eval case `prompt`/input].
  2. Call the TARGET model over an OpenAI-compatible POST {model}/chat/completions
     endpoint, stdlib urllib only (no requests, no pip deps).
  3. GRADE each eval (pluggable):
       assertion  deterministic keyword-coverage proxy derived from the eval's
                  existing `expectations` (and any structured `assert` block) —
                  fully runnable here, no judge model. HONEST about being a proxy.
       judge      POST the rubric (expected_output + expectations) + the model
                  output to a judge endpoint; parse a strict JSON verdict.
       hybrid     assertions where the eval has checkable tokens, else judge.
  4. Classify the skill: PASS (mean score >= threshold) / NEEDS-FINETUNE (below) /
     NO-EVALS (cannot measure — flagged honestly, never counted as a pass).

Emit a Markdown report: a per-skill table (skill | family | #evals | score |
verdict), aggregation by skill-family/cluster, the model-name + quant recorded
prominently, and totals (#pass / #needs-finetune / #no-evals).

Honesty (non-negotiable, mirrors the repo's honesty gating):
  * NEVER fabricate a score. If the endpoint is unreachable the run FAILS LOUDLY
    (exit 2) — no fake passes, no silent skips. A skill whose call errors is
    recorded as ERROR, never as PASS.
  * The model-name + quant are recorded prominently in the report — a number with
    no provenance is not a measurement.
  * NO-EVALS skills are flagged, not invented evals for and not counted as passes.
  * `--selftest` runs entirely against a built-in STUB backend (canned outputs,
    NO network) over a tiny in-repo fixture; it asserts the assertion grader
    PASSES a good canned output and FAILS a planted bad one, classification is
    correct, a report is produced, and no network call happens when stubbed.

Exit codes: baseline -> 0 (report produced; verdicts may include NEEDS-FINETUNE,
that is signal not failure) / 2 (config error or unreachable endpoint).
selftest -> 0 / 1.

Measurement-fidelity upgrades (A-D):
  A. FILE INJECTION — an eval's referenced `files` (paths relative to the skill
     dir) are loaded and appended to the user prompt under a clear delimiter, so
     the model no longer works blind on file-dependent evals. A total 12000-char
     injection budget is enforced (truncate, then note it); a missing/unreadable
     file is injected as a (MISSING) marker, never crashes the run.
  B. NO FAKE 0.0 FOR UNCHECKABLE CASES — a case the assertion grader cannot grade
     (no structured assert, no extractable tokens) now propagates as score None
     and is EXCLUDED from the skill's mean, instead of being scored 0.0 (which
     dishonestly dragged skills to NEEDS-FINETUNE). A skill whose every case is
     ungraded gets the new UNGRADED verdict, NOT NEEDS-FINETUNE; mixed skills
     score the mean of the graded cases and record n_ungraded.
  C. JUDGE/TARGET API KEYS FROM ENV — the judge backend takes its key from
     $JUDGE_API_KEY and the target from $TARGET_API_KEY (if set); key values are
     never printed or logged.
  D. TOOL-DEPENDENT EVAL DETECTION — evals that instruct the model to run scripts
     / execute commands / copy files are not meaningfully measurable single-shot
     against a raw chat-completion model. They are NOT excluded from scoring;
     instead they are flagged in a dedicated report caveats section so a reader
     discounts those scores.
"""
from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import json
import os
import re
import socket
import statistics
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
MANIFEST = REPO_ROOT / "_bmad" / "_config" / "skill-manifest.csv"

DEFAULT_THRESHOLD = 0.8
# (#8) Verdict STABILITY near the threshold. A skill scored on a handful of cases
# can land just over/under the bar by luck — the "todo-app A/B that lost slightly"
# failure. We compute a 1-sigma band (mean ± CI_Z * standard-error-of-the-mean)
# and FLAG the PASS/NEEDS verdict UNSTABLE when that band straddles the threshold:
# the measurement cannot confidently classify it; collect more cases.
CI_Z = 1.0           # band half-width in standard errors of the mean (1-sigma)
LOW_N_MARGIN = 0.15  # with <2 graded cases there is no variance to estimate, so a
#                      lone score this close to the threshold is flagged fragile.
DEFAULT_GRADER = "assertion"
VALID_GRADERS = ("assertion", "judge", "hybrid")
# Trim SKILL.md to a sane system-prompt budget (chars). A SKILL.md can be long;
# the first chunk carries the operative instructions. Recorded in the report.
SYSTEM_PROMPT_BUDGET = 8000
HTTP_TIMEOUT = 300  # seconds; a small model on a busy GPU can be slow on a big
# file-injection prompt. A SINGLE slow/transient response must not abort a whole
# multi-hour run, so transient failures (response timeout, transient 5xx/429,
# connect-timeout, AND a flaky hosted-judge: provider-routing 400s / rate-limit /
# 200-with-no-choices) are retried with backoff before becoming a per-skill ERROR.
HTTP_RETRIES = 4            # total attempts per call on a TRANSIENT failure
HTTP_RETRY_BACKOFF = 5      # seconds; multiplied by the attempt number (5s,10s,15s)
MAX_OUTPUT_TOKENS = 8192    # bound generation so a verbose skill can't run past the
# per-call timeout (a single-shot measurement does not need an unbounded essay).
# Total budget (chars) for injecting an eval case's referenced files into the
# user prompt. Across ALL of a case's files; truncate when exceeded (A).
FILE_INJECTION_BUDGET = 12000

# Verdict labels.
PASS = "PASS"
NEEDS = "NEEDS-FINETUNE"
NO_EVALS = "NO-EVALS"
# A skill that HAS evals but where every case was uncheckable by the grader (no
# structured assert, no extractable tokens). NOT a NEEDS-FINETUNE — there was no
# measurement to fail (B). Never counted as a pass.
UNGRADED = "UNGRADED"
ERROR = "ERROR"


# ── skill families / clusters ────────────────────────────────────────────────
# Coarse clustering used purely for the aggregation view in the report. This is
# a heuristic over the skill name; the real clustering manifest is roadmap item 2
# (informed by THIS baseline). Order matters — first matching prefix/substring wins.
# Org-specific rows (private skill families) live in the optional, never-shipped
# core/private/orchestra-families.yaml and are PREPENDED when present, so they win
# over the generic rows below exactly as if they were listed first.
_PUBLIC_FAMILY_RULES: list[tuple[str, str]] = [
    ("security", "review+security"),
    ("code-review", "review+security"),
    ("review-adversarial", "review+security"),
    ("review-edge-case", "review+security"),
    ("testarch", "test"),
    ("test", "test"),
    ("qa-", "test"),
    ("eval", "eval+governance"),
    ("skill-gov", "eval+governance"),
    ("skill-gap", "eval+governance"),
    ("ux", "design"),
    ("wds-", "design"),
    ("design", "design"),
    ("prd", "planning"),
    ("brief", "planning"),
    ("architect", "planning"),
    ("create-epics", "planning"),
    ("create-story", "planning"),
    ("sprint", "planning"),
    ("spec", "planning"),
    ("brainstorm", "creative"),
    ("storytell", "creative"),
    ("innovation", "creative"),
    ("problem-solv", "creative"),
    ("dev-story", "dev"),
    ("quick-dev", "dev"),
    ("decision-prop", "planning"),
]


PRIVATE_FAMILY_RULES_FILE = REPO_ROOT / "core" / "private" / "orchestra-families.yaml"


def load_private_family_rules(path: Path = PRIVATE_FAMILY_RULES_FILE) -> list[tuple[str, str]]:
    """Read ordered `- "<needle>": "<family>"` rows from the optional private file.
    Stdlib-only (a YAML list of single-key maps; comments/blank lines ignored).
    Absent/unreadable → [] (generic public rules only)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rules: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("- ") or ":" not in line:
            continue
        item = line[2:].strip()
        # Split on the first ':' that follows the (possibly quoted) needle.
        if item[:1] in ("'", '"'):
            q = item[0]
            close = item.find(q, 1)
            if close < 0:
                continue
            needle, rest = item[1:close], item[close + 1:]
            if not rest.lstrip().startswith(":"):
                continue
            fam = rest.lstrip()[1:]
        else:
            needle, fam = item.split(":", 1)
        fam = fam.strip().strip('"').strip("'")
        needle = needle.strip()
        if needle and fam:
            rules.append((needle, fam))
    return rules


FAMILY_RULES: list[tuple[str, str]] = load_private_family_rules() + _PUBLIC_FAMILY_RULES


def family_of(skill_name: str) -> str:
    low = skill_name.lower()
    for needle, fam in FAMILY_RULES:
        if needle in low:
            return fam
    return "other"


# ── eval / skill model ───────────────────────────────────────────────────────


class SkillSpec:
    """A discovered skill: its name, SKILL.md path, its skill dir (for resolving
    eval `files`), and any evals.json cases."""

    def __init__(self, name: str, skill_md: Path | None, evals: list[dict],
                 skill_dir: Path):
        self.name = name
        self.skill_md = skill_md
        self.evals = evals  # list of eval-case dicts (may be empty)
        self.skill_dir = skill_dir  # .claude/skills/<name>/ — base for `files`
        self.family = family_of(name)


def _read_system_prompt(skill_md: Path | None) -> str:
    """SKILL.md, trimmed to the system-prompt budget. Strip the YAML frontmatter
    fence so the instructions (not the metadata) are what the model is primed on."""
    if skill_md is None or not skill_md.is_file():
        return ""
    text = skill_md.read_text(encoding="utf-8", errors="ignore")
    # Strip a leading `---\n ... \n---\n` frontmatter block if present.
    m = re.match(r"^---\n.*?\n---\n", text, re.DOTALL)
    if m:
        text = text[m.end():]
    text = text.strip()
    if len(text) > SYSTEM_PROMPT_BUDGET:
        text = text[:SYSTEM_PROMPT_BUDGET].rstrip() + "\n\n[...SKILL.md truncated for the baseline run...]"
    return text


def build_user_content(ev: dict, skill_dir: Path,
                       budget: int = FILE_INJECTION_BUDGET) -> str:
    """(A) The eval's `prompt` followed by each referenced file's contents under a
    clear delimiter, so the model does not work blind on file-dependent evals.

    `files` entries are paths RELATIVE TO THE SKILL DIR. A TOTAL `budget` (chars)
    is applied across ALL of a case's files; when the budget is exhausted the
    remaining content is truncated and a single truncation note is appended. A
    missing/unreadable file is injected as a `(MISSING)` marker — it must NOT
    crash the run."""
    prompt = ev.get("prompt", "")
    files = [f for f in ev.get("files", []) if isinstance(f, str)]
    if not files:
        return prompt

    parts: list[str] = [prompt]
    remaining = budget
    truncated = False
    for rel in files:
        if remaining <= 0:
            truncated = True
            break
        path = (skill_dir / rel)
        try:
            contents = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError):
            parts.append(f"\n\n----- FILE: {rel} (MISSING) -----\n")
            continue
        header = f"\n\n----- FILE: {rel} -----\n"
        # Account for the header against the budget too, so a tiny budget can't
        # be overrun by headers alone.
        avail = remaining - len(header)
        if avail <= 0:
            truncated = True
            break
        if len(contents) > avail:
            contents = contents[:avail]
            truncated = True
        parts.append(header + contents)
        remaining -= len(header) + len(contents)
    out = "".join(parts)
    if truncated:
        out += "\n[...file(s) truncated for the baseline run...]"
    return out


def _load_evals_json(evals_dir: Path) -> list[dict]:
    """Load + lightly validate evals.json -> its `evals` list. Returns [] if the
    file is missing. Raises ValueError on a malformed file (fail loud, not silent)."""
    f = evals_dir / "evals.json"
    if not f.is_file():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{f}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("evals"), list):
        raise ValueError(f"{f}: expected an object with an 'evals' list")
    cases: list[dict] = []
    for i, ev in enumerate(data["evals"]):
        if not isinstance(ev, dict):
            raise ValueError(f"{f}: eval #{i} is not an object")
        if not isinstance(ev.get("prompt"), str) or not ev["prompt"].strip():
            raise ValueError(f"{f}: eval #{i} missing a non-empty 'prompt'")
        cases.append(ev)
    return cases


def _skill_evals_dir(skill_dir: Path) -> Path:
    """Colocated layout used across this repo: <skill>/evals/evals.json."""
    return skill_dir / "evals"


def discover_skills(skills_root: Path = SKILLS_DIR,
                    pattern: str | None = None) -> list[SkillSpec]:
    """Enumerate skills under .claude/skills/*/ (where SKILL.md + evals/ are
    colocated in this repo), loading each skill's evals.json if present. The
    manifest (skill-manifest.csv) is the catalog of record; this discovery is the
    on-disk view that carries the colocated evals the baseline measures."""
    if not skills_root.is_dir():
        raise ValueError(f"skills root not found: {skills_root}")
    specs: list[SkillSpec] = []
    for skill_dir in sorted(p for p in skills_root.iterdir() if p.is_dir()):
        name = skill_dir.name
        if pattern and not any(
            fnmatch.fnmatch(name, p.strip()) for p in pattern.split(",") if p.strip()
        ):
            continue
        skill_md = skill_dir / "SKILL.md"
        evals = _load_evals_json(_skill_evals_dir(skill_dir))
        specs.append(SkillSpec(name, skill_md if skill_md.is_file() else None,
                               evals, skill_dir))
    return specs


# ── pluggable backend (the key abstraction) ──────────────────────────────────


class Backend:
    """A target-model backend. `chat(system, user)` returns the model's text.
    For multi-turn evals, `chat_messages(messages)` accepts a full message list.
    Single-shot mode (`chat`) is unchanged — only multi-turn mode uses the new method."""

    name = "abstract"

    def chat(self, system: str, user: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def chat_messages(self, messages: list[dict]) -> str:
        """Drive a full message list (multi-turn). Default: extract system+last-user and
        delegate to chat(). Subclasses that natively support multi-turn override this."""
        system = ""
        last_user = ""
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
            elif m.get("role") == "user":
                last_user = m.get("content", "")
        return self.chat(system, last_user)


class OpenAIChatBackend(Backend):
    """An OpenAI-compatible /chat/completions endpoint (vLLM / Ollama /v1 / LM
    Studio all expose one). Stdlib urllib only — NO requests, NO pip deps.

    `base_url` is e.g. http://localhost:11434/v1 ; we POST to base_url +
    /chat/completions. An unreachable endpoint raises BackendError (fail loud)."""

    name = "openai-chat"

    def __init__(self, base_url: str, model_name: str,
                 api_key: str | None = None, timeout: int = HTTP_TIMEOUT,
                 extra_payload: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.api_key = api_key
        self.timeout = timeout
        # Extra top-level payload keys merged into every request (e.g. OpenRouter
        # `provider` routing for the hosted judge). Ignored by endpoints that don't
        # recognize the keys (Ollama/vLLM drop unknown fields).
        self.extra_payload = extra_payload or {}

    def _endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def chat(self, system: str, user: str) -> str:
        """Single-shot two-turn call. Delegates to chat_messages() for DRY retry logic."""
        return self.chat_messages([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])

    def _call_endpoint(self, payload: dict) -> str:
        """Shared HTTP call logic used by both chat() and chat_messages().
        Applies the full retry/backoff policy. Extracted to avoid duplication."""
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self._endpoint(), data=body,
                                     headers=headers, method="POST")
        last_err = "no attempt made"
        for attempt in range(1, HTTP_RETRIES + 1):
            last = attempt == HTTP_RETRIES
            transient = False
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                return data["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", errors="ignore")[:600]
                except Exception:  # noqa: BLE001
                    pass
                last_err = f"HTTP {exc.code}: {detail}"
                low = detail.lower()
                transient = exc.code in (429, 500, 502, 503, 504) or (
                    exc.code == 400 and (
                        "provider returned error" in low
                        or "does not support endpoint" in low
                        or "rate-limit" in low or "rate limit" in low
                        or "temporarily" in low))
                if not (transient and not last):
                    raise BackendError(
                        f"endpoint {self._endpoint()} returned {last_err}") from exc
            except TimeoutError as exc:
                last_err = f"timed out (timeout={self.timeout}s)"
                if last:
                    raise BackendError(
                        f"endpoint {self._endpoint()} timed out after {HTTP_RETRIES} "
                        f"attempts (timeout={self.timeout}s/attempt)") from exc
                transient = True
            except urllib.error.URLError as exc:
                last_err = f"unreachable: {exc.reason}"
                if isinstance(exc.reason, (TimeoutError, socket.timeout)) and not last:
                    transient = True
                else:
                    raise BackendError(
                        f"endpoint {self._endpoint()} unreachable: {exc.reason}") from exc
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                last_err = f"unexpected response shape: {exc}"
                if last:
                    raise BackendError(
                        f"endpoint {self._endpoint()} returned an unexpected shape "
                        f"after {HTTP_RETRIES} attempts: {exc}") from exc
                transient = True
            if transient and not last:
                time.sleep(HTTP_RETRY_BACKOFF * attempt)
        raise BackendError(
            f"endpoint {self._endpoint()} failed after {HTTP_RETRIES} attempts: {last_err}")

    def chat_messages(self, messages: list[dict]) -> str:
        """Multi-turn variant: send the full message list to the endpoint.
        Used by run_multiturn; single-shot `chat()` is unchanged."""
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "stream": False,
        }
        if self.extra_payload:
            payload.update(self.extra_payload)
        return self._call_endpoint(payload)


class StubBackend(Backend):
    """A fake model for --selftest — NO network. Returns canned outputs keyed by a
    marker in the user prompt so the selftest can plant a GOOD and a BAD answer and
    prove the grader distinguishes them. Records every call for the no-network
    assertion.

    For multi-turn evals, chat_messages() scans the FULL message history for
    markers (most-recent-first) so multi-turn stubs can key on any accumulated turn.
    `mt_responses` maps (turn_index, marker) -> canned output for turn-specific replies."""

    name = "stub"

    def __init__(self, responses: dict[str, str], default: str = "",
                 mt_responses: dict[tuple[int, str], str] | None = None):
        self.responses = responses
        self.default = default
        self.calls: list[tuple[str, str]] = []
        # Multi-turn keyed responses: (turn_index, marker) -> canned reply.
        self.mt_responses: dict[tuple[int, str], str] = mt_responses or {}
        self.mt_call_count = 0  # tracks which scripted turn we're on

    def chat(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        for marker, canned in self.responses.items():
            if marker in user:
                return canned
        return self.default

    def chat_messages(self, messages: list[dict]) -> str:
        """Multi-turn variant. Checks mt_responses keyed by (call_count, marker),
        falling back to scanning all user messages for a single-shot marker match."""
        # Concatenate all user content for marker scanning.
        all_user = " ".join(
            m.get("content", "") for m in messages if m.get("role") == "user"
        )
        last_user = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        turn = self.mt_call_count
        self.mt_call_count += 1
        self.calls.append(("", last_user))

        # Check turn-specific keyed responses first.
        for (t, marker), canned in self.mt_responses.items():
            if t == turn and marker in all_user:
                return canned

        # Fall back to the single-shot marker scan over all user content.
        for marker, canned in self.responses.items():
            if marker in all_user:
                return canned
        return self.default


class BackendError(RuntimeError):
    """Raised when a backend call cannot produce a real answer. Fail loud."""


# ── multi-turn + mock-tool eval mode ─────────────────────────────────────────
#
# WHAT THIS MEASURES: reasoning and dispatch intent — does the model emit the
# correct tool-call at the correct turn in a scripted conversation?
#
# WHAT THIS CANNOT MEASURE (honesty boundary — never claim otherwise):
#   * Genuine parallel subagent independence (bmad-party-mode)
#   * Real filesystem effects — whether progress/ was actually written
#   * Real git operations — commits, merges, CI runs
#   * Actual installer script execution (bmad-bmb-setup, sync)
#   * Cross-machine / cross-session state durability
#   * Any skill requiring a real external service, network, or subprocess
#
# Tool-call protocol: the model emits calls in structured plain text (no native
# function-calling required) so any OpenAI-compatible endpoint works:
#
#   TOOL_CALL: {"tool": "write_file", "args": {"path": "progress/saga.md", ...}}
#
# The harness detects the TOOL_CALL: prefix, parses the JSON, looks up the tool
# in the mock registry, injects the canned response as a TOOL_RESULT: user turn,
# and records the call. An unparseable tool call FAILS CLOSED — never silently
# passes.


@dataclasses.dataclass
class ToolCallRecord:
    """One tool call emitted by the model during a multi-turn eval."""
    turn_index: int   # 0-indexed into ev["conversation"]
    tool_name: str    # as parsed from TOOL_CALL JSON
    args: dict        # as parsed from TOOL_CALL JSON (may be empty)


# Regex to detect a tool call in assistant output. Anchored to start of a line
# so incidental mentions of "TOOL_CALL" in prose do not fire.
TOOL_CALL_RE = re.compile(r"^TOOL_CALL:\s*(\{.*\})", re.MULTILINE)


def _parse_tool_call(text: str) -> ToolCallRecord | None:
    """Extract the first TOOL_CALL from text. Returns None if none found.
    Returns a ToolCallRecord with turn_index=-1 (caller sets real index).
    Fails closed: if JSON is present but unparseable, returns a sentinel record
    with tool_name='__malformed__' so the caller can record a grading failure."""
    m = TOOL_CALL_RE.search(text)
    if m is None:
        return None
    raw_json = m.group(1).strip()
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        # Malformed JSON — fail closed: return a sentinel that the grader records
        # as a failure. NEVER silently pass a malformed tool call.
        return ToolCallRecord(turn_index=-1, tool_name="__malformed__",
                              args={"raw": raw_json[:200]})
    if not isinstance(parsed, dict) or "tool" not in parsed:
        return ToolCallRecord(turn_index=-1, tool_name="__malformed__",
                              args={"raw": raw_json[:200]})
    return ToolCallRecord(turn_index=-1, tool_name=str(parsed["tool"]),
                          args=parsed.get("args", {}))


def run_multiturn(
    system: str,
    ev: dict,
    backend: Backend,
    tools: dict[str, dict],
) -> tuple[list[dict], list[ToolCallRecord]]:
    """Drive a multi-turn eval. Returns (transcript_messages, tool_calls_recorded).

    transcript_messages = list of:
      {"role": "user"|"assistant"|"tool_result", "content": str}

    tool_calls_recorded = list of ToolCallRecord (one per detected call, with real
    turn_index set). Malformed calls ARE recorded (tool_name='__malformed__') so
    the grader can mark them as failures — they NEVER silently pass.

    Raises BackendError on any backend failure. A BackendError = ERROR, never PASS.

    HONESTY: this function cannot measure real filesystem effects, git operations,
    subprocess execution, or parallel subagent independence. It measures only
    whether the model emits the correct structured text at the correct turn.
    """
    scripted_turns: list[dict] = ev.get("conversation", [])
    transcript: list[dict] = []
    tool_calls: list[ToolCallRecord] = []

    # Accumulated message history sent to the model.
    messages: list[dict] = [{"role": "system", "content": system}]

    for turn_index, scripted in enumerate(scripted_turns):
        user_content = scripted.get("content", "")

        # 1. Inject scripted user message.
        messages.append({"role": "user", "content": user_content})
        transcript.append({"role": "user", "content": user_content})

        # 2. Call the model with the full accumulated history.
        #    BackendError propagates to the caller (recorded as ERROR).
        assistant_output = backend.chat_messages(messages)

        # 3. Parse any tool call from the assistant's output.
        tc = _parse_tool_call(assistant_output)
        if tc is not None:
            tc.turn_index = turn_index
            tool_calls.append(tc)

            # 4a. Look up tool in mock registry. Unknown tools get an error response
            #     (still recorded) — not a crash.
            if tc.tool_name == "__malformed__":
                tool_response = "TOOL_RESULT: ERROR: malformed tool call (JSON parse failed)"
            elif tc.tool_name in tools:
                tool_response = f"TOOL_RESULT: {tools[tc.tool_name]['response']}"
            else:
                tool_response = f"TOOL_RESULT: ERROR: unknown tool '{tc.tool_name}'"

            # 4b. Inject tool result as a user-role message (maximally compatible with
            #     all OpenAI-compatible endpoints, including Ollama/vLLM small models).
            messages.append({"role": "assistant", "content": assistant_output})
            messages.append({"role": "user", "content": tool_response})
            transcript.append({"role": "assistant", "content": assistant_output})
            transcript.append({"role": "tool_result", "content": tool_response})
        else:
            # No tool call in this turn.
            messages.append({"role": "assistant", "content": assistant_output})
            transcript.append({"role": "assistant", "content": assistant_output})

    return transcript, tool_calls


def grade_multiturn(
    ev: dict,
    transcript: list[dict],
    tool_calls: list[ToolCallRecord],
    grader: str,
    judge: Backend | None,
) -> tuple[float | None, str, list[str]]:
    """Grade a completed multi-turn transcript.

    Returns (score in [0,1] or None, grader_used, evidence_lines).

    Two phases:
    1. Deterministic tool-call assertions (assert_tool_calls). If any fail, the
       phase-1 score is below 1.0. A malformed tool call counts as a failure for
       any assertion at that turn.
    2. Transcript assertion/judge grade (same semantics as single-shot grade_case,
       applied to the concatenated transcript).

    Final score = mean(phase1_score, phase2_score) when both exist, else whichever
    is present. This is conservative: a perfect transcript grade cannot compensate
    for missing required tool calls (phase 1 failure caps the score at <= 0.5 when
    any required tool call is missed).

    HONESTY rules:
    - An unparseable tool call (tool_name='__malformed__') counts as a FAIL for
      any assert_tool_calls entry at that turn.
    - If assert_tool_calls is present and ANY entry fails, overall score <= 0.5.
    - BackendError is never caught here; it propagates to the caller as ERROR.
    """
    evidence: list[str] = []
    assert_entries: list[dict] = ev.get("assert_tool_calls", [])

    # ── Phase 1: deterministic tool-call assertions ──
    phase1_score: float | None = None
    if assert_entries:
        passed = 0
        for entry in assert_entries:
            req_turn = entry.get("turn", -1)
            req_tool = entry.get("tool", "")
            # Find all tool calls at this turn.
            calls_at_turn = [tc for tc in tool_calls if tc.turn_index == req_turn]
            # A __malformed__ call at this turn is a failure (fail closed).
            if any(tc.tool_name == req_tool for tc in calls_at_turn
                   if tc.tool_name != "__malformed__"):
                passed += 1
            else:
                actual = [tc.tool_name for tc in calls_at_turn] or ["(none)"]
                evidence.append(
                    f"assert_tool_calls[turn={req_turn}]: expected '{req_tool}', "
                    f"got {actual}"
                )
                if any(tc.tool_name == "__malformed__" for tc in calls_at_turn):
                    evidence.append(
                        f"  turn {req_turn}: malformed TOOL_CALL JSON — fails closed"
                    )
        phase1_score = passed / len(assert_entries)

    # ── Phase 2: transcript-level assertion or judge grade ──
    # Flatten transcript to a single string for the grader.
    flat_transcript = "\n".join(
        f"[{m['role'].upper()}] {m['content']}" for m in transcript
    )
    # Build a synthetic eval dict for the grader functions (reuse existing graders).
    transcript_ev = {
        "expected_output": ev.get("expected_output", ""),
        "expectations": ev.get("expectations", []),
        "assert": ev.get("assert"),  # pass through any structured assert too
    }
    phase2_score: float | None = None
    phase2_grader = grader
    if grader == "assertion":
        s, ev_lines = assertion_grade(transcript_ev, flat_transcript)
        phase2_score = s
        evidence.extend(ev_lines)
    elif grader == "judge":
        if judge is None:
            evidence.append("judge grader selected but no judge backend (phase 2 skipped)")
        else:
            s, ev_lines = judge_grade(transcript_ev, flat_transcript, judge)
            phase2_score = s
            evidence.extend(ev_lines)
    elif grader == "hybrid":
        s, ev_lines = assertion_grade(transcript_ev, flat_transcript)
        if s is not None:
            phase2_score = s
            phase2_grader = "assertion"
            evidence.extend(ev_lines)
        elif judge is not None:
            s, ev_lines = judge_grade(transcript_ev, flat_transcript, judge)
            phase2_score = s
            phase2_grader = "judge"
            evidence.extend(ev_lines)
        else:
            evidence.append("hybrid: nothing checkable and no judge backend (phase 2 skipped)")

    # ── Combine phases ──
    # Hard gate (honesty): a deterministic tool-call assertion is a REQUIRED
    # behavior — if any failed, the case CANNOT pass however well the transcript
    # reads. Cap the final score <= 0.5 (below the 0.80 bar) whenever phase 1 is
    # present and imperfect, in EVERY branch (incl. tool-calls-only, where a raw
    # fraction like 4/5 would otherwise sneak a missed required call past the bar).
    tool_gate_failed = phase1_score is not None and phase1_score < 1.0
    if phase1_score is not None and phase2_score is not None:
        combined = (phase1_score + phase2_score) / 2.0
        if tool_gate_failed:
            combined = min(combined, 0.5)
        return combined, f"multi-turn({phase2_grader})", evidence
    elif phase1_score is not None:
        score = min(phase1_score, 0.5) if tool_gate_failed else phase1_score
        return score, "multi-turn(tool-calls-only)", evidence
    elif phase2_score is not None:
        return phase2_score, f"multi-turn({phase2_grader})", evidence
    else:
        return None, "multi-turn(none-checkable)", evidence


# ── graders ───────────────────────────────────────────────────────────────────


# (D) Tool-dependent eval detection. Some evals instruct the model to RUN scripts
# / execute commands / COPY files — a raw chat-completion model has no tools, so
# these are not meaningfully measurable single-shot. We do NOT exclude them from
# scoring; we FLAG them so a reader discounts those scores. A TIGHT marker set
# (avoid false positives on prose that merely mentions "run"):
#   * a backticked shell/python COMMAND: `run ...` or `python3 ...` inside `...`
#   * the phrase "run headless"
#   * the phrase "capture its output"
#   * the phrase "COPY the"
# An IMPERATIVE instruction to execute a backticked command/script, e.g.
# "Run `python3 .../foo.py ...`". Requires an execute-verb (whole word, so a
# generated artifact that merely "runs `npm test`" does NOT match) shortly before a
# backticked script/command. This isolates evals that truly need tools from those
# that only reference commands in their expected output, and "run headless" (no
# backticked command) is likewise not matched. Deliberately UNDER-flags so the
# caveat stays trustworthy.
_TOOL_RUN_RE = re.compile(
    r"\b(?:run|execute|invoke)\b[^`\n]{0,30}`[^`]*"
    r"(?:\bpython3?\b|\bpytest\b|\bnode\b|\bnpm\b|\bnpx\b|\bbash\b|\bsh\b|\./|\.py\b)[^`]*`",
    re.IGNORECASE,
)


def is_tool_dependent(prompt: str) -> bool:
    """True only if the prompt IMPERATIVELY instructs the model to execute a
    backticked command/script (e.g. "Run `python3 .../foo.py`") -- work a single-
    shot chat completion cannot do (D). Whole-word execute-verbs mean a generated
    artifact that merely 'runs `npm test`' is NOT flagged; 'run headless' has no
    backticked command and is not flagged either."""
    if not prompt:
        return False
    return bool(_TOOL_RUN_RE.search(prompt))


# Token-extraction for the assertion grader: pull literal tokens the model output
# must contain out of an expectation string. We take BACKTICKED `tokens` and
# "quoted" / 'quoted' literals — these are the load-bearing concrete strings an
# eval author writes (identifiers, section names, verdict labels). Pure prose with
# no such token yields nothing checkable (honest: that expectation is not gradeable
# by assertions and is reported as such).
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_DQUOTE_RE = re.compile(r'"([^"]+)"')
_SQUOTE_RE = re.compile(r"'([^']+)'")


def extract_assertion_tokens(expectation: str) -> list[str]:
    toks: list[str] = []
    for rgx in (_BACKTICK_RE, _DQUOTE_RE, _SQUOTE_RE):
        for m in rgx.findall(expectation):
            t = m.strip()
            # Skip trivially-short or whitespace-only tokens to avoid false hits.
            if len(t) >= 2:
                toks.append(t)
    # De-dup, preserve order.
    seen: set[str] = set()
    out: list[str] = []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def assertion_grade(ev: dict, output: str) -> tuple[float | None, list[str]]:
    """Deterministic keyword-coverage proxy for ONE eval case.

    Source of truth, in order:
      1. A structured `assert` block on the eval (first-class, exact):
           {"contains": [...], "not_contains": [...]}
         Every `contains` token must appear; no `not_contains` token may.
      2. Else: tokens extracted from each `expectations[]` string (backticked /
         quoted literals). An expectation contributes a sub-score = fraction of
         its tokens present in the output; the case score is their mean.

    Returns (score in [0,1] or None if NOTHING is checkable, evidence lines).
    HONEST: when an eval has no structured assert and no extractable tokens, the
    assertion grader returns None — it does not pretend to have measured."""
    evidence: list[str] = []
    out = output or ""

    # 1. Structured assert block (exact, first-class).
    block = ev.get("assert")
    if isinstance(block, dict):
        contains = [s for s in block.get("contains", []) if isinstance(s, str)]
        not_contains = [s for s in block.get("not_contains", []) if isinstance(s, str)]
        hits = 0
        total = len(contains) + len(not_contains)
        for s in contains:
            if s in out:
                hits += 1
            else:
                evidence.append(f"missing required {s!r}")
        for s in not_contains:
            if s not in out:
                hits += 1
            else:
                evidence.append(f"contains forbidden {s!r}")
        if total == 0:
            return None, ["assert block present but empty"]
        return hits / total, evidence

    # 2. Expectations-derived tokens.
    expectations = [e for e in ev.get("expectations", []) if isinstance(e, str)]
    sub_scores: list[float] = []
    for exp in expectations:
        toks = extract_assertion_tokens(exp)
        if not toks:
            continue  # not checkable by assertions; honestly skipped
        present = [t for t in toks if t in out]
        frac = len(present) / len(toks)
        sub_scores.append(frac)
        if frac < 1.0:
            missing = [t for t in toks if t not in out]
            evidence.append(f"expectation tokens missing: {missing}")
    if not sub_scores:
        return None, ["no structured assert and no extractable tokens (not gradeable by assertions)"]
    return sum(sub_scores) / len(sub_scores), evidence


def _extract_json_verdict(raw: str) -> dict:
    """Pull the judge's JSON verdict out of a response that may wrap it in prose
    preamble ("Looking at the output: ...") or markdown ```json fences. Scans every
    balanced {...} substring and returns the LAST one that parses and carries the
    verdict keys — robust to a chatty judge (e.g. Claude reasoning before the JSON).
    Raises ValueError if none is found."""
    s = raw.strip()
    # Drop surrounding markdown code fences if present.
    s = re.sub(r"```(?:json)?", "", s)
    candidates: list[str] = []
    for st in (i for i, c in enumerate(s) if c == "{"):
        depth = 0
        for j in range(st, len(s)):
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(s[st:j + 1])
                    break
    # Prefer the last balanced object carrying the verdict keys; else any dict.
    for cand in reversed(candidates):
        try:
            d = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(d, dict) and "passed" in d and "total" in d:
            return d
    for cand in reversed(candidates):
        try:
            d = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(d, dict):
            return d
    # Fallback: the judge emitted the canonical numeric verdict but the JSON is not
    # a balanced/parseable object — typically a truncated response (no closing brace)
    # or an unescaped quote/newline/brace inside `notes`. `passed`/`total` are the
    # load-bearing fields (notes is cosmetic) and the grader prompt places them first,
    # so recover them directly rather than DROP a real grade to ERROR (which silently
    # corrupts the baseline). Fails closed (ValueError) only if the integers are
    # genuinely absent. The recovered notes flags that repair happened, for audit.
    p = re.findall(r'"passed"\s*:\s*(\d+)', s)
    t = re.findall(r'"total"\s*:\s*(\d+)', s)
    if p and t:
        return {
            "passed": int(p[-1]),
            "total": int(t[-1]),
            "notes": "[verdict recovered from malformed/truncated judge JSON]",
        }
    raise ValueError("no parseable JSON verdict object found")


def judge_grade(ev: dict, output: str, judge: Backend) -> tuple[float, list[str]]:
    """Ask a judge model to score the output against the eval's rubric. Returns
    (score in [0,1], evidence). Mirrors bmad-eval-runner's model-judge approach.
    A judge that errors propagates BackendError (fail loud — never default-pass)."""
    expectations = [e for e in ev.get("expectations", []) if isinstance(e, str)]
    rubric = "\n".join(f"- {e}" for e in expectations) or "- (no explicit expectations)"
    system = (
        "You are a strict eval grader. Given an eval's expected outcome, its "
        "expectations, and a candidate model output, decide how well the output "
        "meets EACH expectation. Burden of proof is on the output; when unsure, "
        "fail. Your ENTIRE response MUST be a single JSON object and nothing else "
        "— no preamble, no explanation, no markdown fences. Emit `passed` and "
        "`total` FIRST. Keep `notes` to ONE short clause (<= 20 words), plain ASCII, "
        "with NO double-quote characters, newlines, or braces inside it, so the JSON "
        "stays well-formed and parseable: "
        '{"passed": <int>, "total": <int>, "notes": "<short>"}.'
    )
    user = (
        f"EXPECTED OUTCOME:\n{ev.get('expected_output', '(none)')}\n\n"
        f"EXPECTATIONS:\n{rubric}\n\n"
        f"CANDIDATE OUTPUT:\n{output}\n\n"
        "Respond with ONLY the JSON object — no other text."
    )
    raw = judge.chat(system, user)
    try:
        verdict = _extract_json_verdict(raw)
        passed = int(verdict["passed"])
        total = int(verdict["total"])
    except (ValueError, KeyError, TypeError) as exc:
        raise BackendError(f"judge verdict unparseable: {exc}; raw={raw[:300]!r}") from exc
    if total <= 0:
        return 0.0, [verdict.get("notes", "")]
    return passed / total, [verdict.get("notes", "")]


def grade_case(ev: dict, output: str, grader: str,
               judge: Backend | None) -> tuple[float | None, str, list[str]]:
    """Grade ONE eval case with the chosen grader policy.
    Returns (score, grader_used, evidence).

    (B) HONESTY: an uncheckable assertion/hybrid-without-judge case returns score
    None (a sentinel for "not gradeable by this grader") — NOT 0.0. The caller
    EXCLUDES None-scored cases from the mean rather than dragging the skill to
    NEEDS-FINETUNE over an absence of measurement. (The judge grader always
    returns a real number, so None only arises for assertion / hybrid-without-
    judge.)"""
    if grader == "assertion":
        score, ev_lines = assertion_grade(ev, output)
        if score is None:
            # Nothing checkable — propagate None (not a fake 0.0); excluded from
            # the mean and surfaced via the UNGRADED verdict where it dominates.
            return None, "assertion(none-checkable)", \
                ["assertion grader had nothing checkable for this case"] + ev_lines
        return score, "assertion", ev_lines
    if grader == "judge":
        if judge is None:
            raise ValueError("judge grader selected but no judge backend configured")
        score, ev_lines = judge_grade(ev, output, judge)
        return score, "judge", ev_lines
    if grader == "hybrid":
        score, ev_lines = assertion_grade(ev, output)
        if score is not None:
            return score, "assertion", ev_lines
        if judge is None:
            # No judge available for a non-checkable case — propagate None (B)
            # rather than fabricate a score; it is excluded from the mean.
            return None, "hybrid(none-checkable)", \
                ["hybrid had nothing checkable and no judge backend"] + ev_lines
        jscore, jev = judge_grade(ev, output, judge)
        return jscore, "judge", jev
    raise ValueError(f"unknown grader {grader!r}")


# ── baseline run ──────────────────────────────────────────────────────────────


class SkillResult:
    def __init__(self, spec: SkillSpec):
        self.spec = spec
        self.n_evals = len(spec.evals)
        self.case_scores: list[float] = []  # GRADED cases only (None excluded)
        self.n_ungraded = 0  # (B) cases the grader could not grade (score None)
        # (D) tool-dependent cases: count + their ids, for the report caveat.
        self.n_tool_dependent = 0
        self.tool_dependent_ids: list[str] = []
        self.verdict = NO_EVALS
        self.score: float | None = None
        self.error: str | None = None
        # (#8) verdict-stability band around the mean (set when graded).
        self.ci_low: float | None = None
        self.ci_high: float | None = None
        self.unstable = False
        # (#22) trace-as-gradient: the eval evidence for cases that scored BELOW
        # the bar, captured so the improvement/teacher step gets the diagnostic
        # (WHY it failed), not just the pass/fail score.
        self.failure_evidence: list[str] = []

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def family(self) -> str:
        return self.spec.family


def _stability(scores: list[float], threshold: float) -> tuple[float | None, float | None, bool]:
    """(#8) Return (ci_low, ci_high, unstable) for a list of graded case scores.

    A 1-sigma band (mean ± CI_Z * SEM) around the mean; `unstable` is True when
    that band straddles the threshold, so the PASS/NEEDS verdict sits within the
    measurement's own noise. With a single case there is no variance to estimate,
    so a lone score within LOW_N_MARGIN of the threshold is flagged fragile.
    Returns (None, None, False) for an empty list (nothing measured)."""
    n = len(scores)
    if n == 0:
        return None, None, False
    mean = sum(scores) / n
    if n >= 2:
        sd = statistics.pstdev(scores)
        half = CI_Z * sd / (n ** 0.5)
        lo, hi = max(0.0, mean - half), min(1.0, mean + half)
        return lo, hi, (lo < threshold <= hi)
    return mean, mean, abs(mean - threshold) < LOW_N_MARGIN


def run_baseline(specs: list[SkillSpec], backend: Backend, *,
                 grader: str = DEFAULT_GRADER, judge: Backend | None = None,
                 threshold: float = DEFAULT_THRESHOLD,
                 limit: int | None = None) -> list[SkillResult]:
    """Drive `backend` over each skill's evals and classify. An ERROR on a real
    backend call is recorded (never silently passed); the CALLER decides whether to
    fail the whole run (it does, for the OpenAI backend — fail loud)."""
    results: list[SkillResult] = []
    for spec in specs:
        res = SkillResult(spec)
        if not spec.evals:
            res.verdict = NO_EVALS
            results.append(res)
            continue
        system = _read_system_prompt(spec.skill_md)
        cases = spec.evals if limit is None else spec.evals[:limit]
        try:
            for ev in cases:
                # (D) flag tool-dependent cases (still scored, just discounted).
                if is_tool_dependent(ev.get("prompt", "")):
                    res.n_tool_dependent += 1
                    res.tool_dependent_ids.append(str(ev.get("id", "?")))

                if ev.get("mode") == "multi-turn":
                    # ── Multi-turn eval path ──────────────────────────────────
                    # Drives the model turn-by-turn with mock tool dispatch.
                    # BackendError propagates upward = ERROR (never PASS).
                    tools_registry = {
                        k: v for k, v in ev.get("tools", {}).items()
                        if isinstance(v, dict)
                    }
                    transcript, tool_calls = run_multiturn(
                        system, ev, backend, tools_registry
                    )
                    score, _used, _evid = grade_multiturn(
                        ev, transcript, tool_calls, grader, judge
                    )
                else:
                    # ── Single-shot eval path (unchanged) ────────────────────
                    # (A) inject the eval's referenced files into the user prompt.
                    user = build_user_content(ev, spec.skill_dir)
                    output = backend.chat(system, user)
                    score, _used, _evid = grade_case(ev, output, grader, judge)

                if score is None:
                    # (B) ungraded — excluded from the mean, tracked separately.
                    res.n_ungraded += 1
                else:
                    res.case_scores.append(score)
                    # (#22) keep the evidence for sub-threshold cases as the
                    # trace-as-gradient input (capped, tagged by case id).
                    if score < threshold and _evid and len(res.failure_evidence) < 8:
                        cid = str(ev.get("id", "?"))
                        res.failure_evidence.append(
                            f"[{cid}] (score {score:.2f}) "
                            + "; ".join(str(e) for e in _evid[:3]))
        except BackendError as exc:
            res.verdict = ERROR
            res.error = str(exc)
            results.append(res)
            continue
        if res.case_scores:
            # Mean of GRADED cases; ungraded ones do not drag the score (B).
            res.score = sum(res.case_scores) / len(res.case_scores)
            res.verdict = PASS if res.score >= threshold else NEEDS
            # (#8) flag a verdict that sits within measurement noise of the bar.
            res.ci_low, res.ci_high, res.unstable = _stability(res.case_scores, threshold)
        elif res.n_ungraded:
            # Had evals, but every case was uncheckable — no measurement to fail.
            res.verdict = UNGRADED
        else:
            res.verdict = NO_EVALS
        results.append(res)
    return results


# ── report ────────────────────────────────────────────────────────────────────


def _fmt_score(s: float | None) -> str:
    return "—" if s is None else f"{s:.2f}"


def render_report(results: list[SkillResult], *, model_name: str, model_url: str,
                  quant: str | None, grader: str, threshold: float,
                  limit: int | None) -> str:
    measurable = [r for r in results if r.verdict in (PASS, NEEDS)]
    n_pass = sum(1 for r in results if r.verdict == PASS)
    n_needs = sum(1 for r in results if r.verdict == NEEDS)
    n_noevals = sum(1 for r in results if r.verdict == NO_EVALS)
    n_ungraded = sum(1 for r in results if r.verdict == UNGRADED)
    n_error = sum(1 for r in results if r.verdict == ERROR)
    n_unstable = sum(1 for r in results if getattr(r, "unstable", False))

    lines: list[str] = []
    lines.append("# Orchestra baseline report")
    lines.append("")
    lines.append(
        "Generated by `wf orchestra baseline` — see `docs/orchestra/specialist-orchestra.md` §3. "
        "A measurement of which skills a *prompted* small model already passes vs. which "
        "need fine-tuning. **No score is fabricated**; an unreachable endpoint fails the run."
    )
    lines.append("")
    # Model + quant recorded PROMINENTLY (a number with no provenance is not a measurement).
    lines.append("## Model under test")
    lines.append("")
    lines.append(f"- **Model name:** `{model_name}`")
    lines.append(f"- **Quantization:** `{quant or 'unspecified'}`")
    lines.append(f"- **Endpoint:** `{model_url}`")
    lines.append(f"- **Grader:** `{grader}`")
    lines.append(f"- **Max output tokens:** `{MAX_OUTPUT_TOKENS}` (per-response generation cap)")
    lines.append(f"- **Pass threshold:** `{threshold:.2f}` (mean case score >= threshold)")
    if limit is not None:
        lines.append(f"- **Per-skill eval limit:** `{limit}`")
    lines.append("")

    # Totals.
    lines.append("## Totals")
    lines.append("")
    lines.append(f"- **PASS (no fine-tune needed):** {n_pass}")
    lines.append(f"- **NEEDS-FINETUNE:** {n_needs}")
    lines.append(f"- **NO-EVALS (cannot measure — flagged honestly):** {n_noevals}")
    lines.append(
        f"- **UNGRADED (has evals but no case was checkable — NOT a NEEDS-FINETUNE, "
        f"never counted as a pass):** {n_ungraded}"
    )
    if n_error:
        lines.append(f"- **ERROR (call failed — NOT counted as pass):** {n_error}")
    lines.append(
        f"- **UNSTABLE (PASS/NEEDS verdict within measurement noise of the "
        f"threshold — collect more cases before trusting it):** {n_unstable}"
    )
    lines.append(f"- **Skills measured:** {len(measurable)} of {len(results)} discovered")
    lines.append("")

    # Aggregation by family / cluster.
    lines.append("## By skill family / cluster")
    lines.append("")
    lines.append("| Family | #skills | #pass | #needs-finetune | #ungraded | #no-evals | mean score (measured) |")
    lines.append("|--------|--------:|------:|----------------:|----------:|----------:|----------------------:|")
    fams: dict[str, list[SkillResult]] = {}
    for r in results:
        fams.setdefault(r.family, []).append(r)
    for fam in sorted(fams):
        members = fams[fam]
        fp = sum(1 for r in members if r.verdict == PASS)
        fn = sum(1 for r in members if r.verdict == NEEDS)
        # UNGRADED does not count as pass or needs — it is its own column.
        fu = sum(1 for r in members if r.verdict == UNGRADED)
        fne = sum(1 for r in members if r.verdict == NO_EVALS)
        scored = [r.score for r in members if r.score is not None]
        mean = f"{sum(scored) / len(scored):.2f}" if scored else "—"
        lines.append(f"| {fam} | {len(members)} | {fp} | {fn} | {fu} | {fne} | {mean} |")
    lines.append("")

    # Per-skill table.
    lines.append("## Per-skill")
    lines.append("")
    lines.append("| Skill | Family | #evals | Score | Verdict |")
    lines.append("|-------|--------|-------:|------:|---------|")
    for r in sorted(results, key=lambda x: (x.family, x.name)):
        note = ""
        if r.verdict == ERROR and r.error:
            note = f" <!-- {r.error} -->"
        vlabel = r.verdict + (" ⚠UNSTABLE" if getattr(r, "unstable", False) else "")
        if getattr(r, "unstable", False) and r.ci_low is not None:
            note += f" <!-- 1σ band [{r.ci_low:.2f},{r.ci_high:.2f}] straddles {threshold:.2f} -->"
        lines.append(
            f"| `{r.name}` | {r.family} | {r.n_evals} | {_fmt_score(r.score)} | "
            f"{vlabel} |{note}"
        )
    lines.append("")
    lines.append(
        "> NO-EVALS skills cannot be measured by this harness and are flagged, never "
        "counted as a pass. UNGRADED skills HAVE evals but no case was checkable by "
        "the grader — there was no measurement to fail, so they are NOT NEEDS-FINETUNE "
        "and are never counted as a pass. NEEDS-FINETUNE is signal (the fine-tuning "
        "workload), not a harness failure. ERROR rows mean the call failed and are "
        "never a pass. A ⚠UNSTABLE flag means the verdict's 1σ confidence band "
        "straddles the threshold — the PASS/NEEDS call is within the measurement's "
        "own noise, so collect more cases before trusting it."
    )
    lines.append("")

    # (#22) Failure evidence — the trace-as-gradient input for the improvement step.
    needs_ev = [r for r in results
                if r.verdict == NEEDS and getattr(r, "failure_evidence", None)]
    if needs_ev:
        lines.append("## Failure evidence (trace-as-gradient input for NEEDS-FINETUNE)")
        lines.append("")
        lines.append(
            "The eval DIAGNOSTIC for each failing skill — route THIS into the "
            "improvement/teacher step (the WHY), not just the pass/fail score "
            "(orchestration.finetune_from_verified_traces). Verifier-gated: these are "
            "assertion/judge failures, not self-reported uncertainty."
        )
        lines.append("")
        for r in sorted(needs_ev, key=lambda x: (x.family, x.name)):
            lines.append(f"- `{r.name}` ({r.family}):")
            for e in r.failure_evidence[:5]:
                lines.append(f"    - {e}")
        lines.append("")
    lines.append("")

    # (D) Caveats — tool-dependent evals (not single-shot measurable).
    lines.append("## Caveats — tool-dependent evals (not single-shot measurable)")
    lines.append("")
    lines.append(
        "These evals instruct the model to run scripts, execute commands, or copy "
        "files — a raw chat-completion model has no tools, so their scores are NOT a "
        "fair single-shot measurement and should be discounted. They are still scored "
        "(not excluded); they are listed here so a reader knows to weight them lightly."
    )
    lines.append("")
    tool_dep = [r for r in sorted(results, key=lambda x: (x.family, x.name))
                if r.n_tool_dependent]
    if not tool_dep:
        lines.append("none")
    else:
        lines.append("| Skill | #tool-dependent cases | case ids |")
        lines.append("|-------|----------------------:|----------|")
        for r in tool_dep:
            ids = ", ".join(f"`{i}`" for i in r.tool_dependent_ids)
            lines.append(f"| `{r.name}` | {r.n_tool_dependent} | {ids} |")
    lines.append("")
    return "\n".join(lines)


# ── CLI: baseline ─────────────────────────────────────────────────────────────


def cmd_baseline(args: argparse.Namespace) -> int:
    grader = args.grader
    if grader not in VALID_GRADERS:
        sys.stderr.write(f"wf orchestra: unknown grader {grader!r}\n")
        return 2
    if grader in ("judge", "hybrid") and not args.judge_model:
        sys.stderr.write(
            f"wf orchestra: grader '{grader}' requires --judge-model <url>\n"
        )
        return 2

    try:
        specs = discover_skills(pattern=args.skills)
    except ValueError as exc:
        sys.stderr.write(f"wf orchestra: {exc}\n")
        return 2
    if not specs:
        sys.stderr.write("wf orchestra: no skills discovered\n")
        return 2

    # (C) API keys from the environment (never printed/logged). The target key is
    # optional ($TARGET_API_KEY); the judge key is $JUDGE_API_KEY.
    backend = OpenAIChatBackend(args.model, args.model_name,
                                api_key=os.environ.get("TARGET_API_KEY"))
    judge: Backend | None = None
    if args.judge_model:
        # OpenRouter provider routing: only route the judge to providers that
        # support the request's parameters, and skip a provider observed to reject
        # this model on /chat/completions ("does not support endpoint: completions").
        # This removes the dominant baseline-error class (flaky provider fallback).
        # Harmless on non-OpenRouter judge endpoints (the key is simply ignored).
        judge = OpenAIChatBackend(args.judge_model,
                                  args.judge_model_name or args.model_name,
                                  api_key=os.environ.get("JUDGE_API_KEY"),
                                  extra_payload={"provider": {
                                      "require_parameters": True,
                                      "ignore": ["Novita"],
                                      "allow_fallbacks": True,
                                  }})

    # Fail loud on an unreachable endpoint BEFORE claiming any result: probe the
    # target with a trivial call. (Honesty: no fake passes against a dead endpoint.)
    measurable = [s for s in specs if s.evals]
    if measurable:
        try:
            backend.chat("ping", "Reply with: ok")
        except BackendError as exc:
            sys.stderr.write(
                f"wf orchestra: target endpoint unreachable — FAILING the run "
                f"(no fake passes).\n  {exc}\n"
            )
            return 2

    results = run_baseline(
        specs, backend, grader=grader, judge=judge,
        threshold=args.threshold, limit=args.limit,
    )

    # If ANY measurable skill errored on a real call, fail loud — a partial run with
    # silent ERROR rows would understate the workload dishonestly.
    errored = [r for r in results if r.verdict == ERROR]
    report = render_report(
        results, model_name=args.model_name, model_url=args.model,
        quant=args.quant, grader=grader, threshold=args.threshold, limit=args.limit,
    )
    out_path = Path(args.out).expanduser().resolve() if args.out else None
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"wf orchestra: wrote report -> {out_path}")
    else:
        print(report)

    n_pass = sum(1 for r in results if r.verdict == PASS)
    n_needs = sum(1 for r in results if r.verdict == NEEDS)
    n_noevals = sum(1 for r in results if r.verdict == NO_EVALS)
    n_ungraded = sum(1 for r in results if r.verdict == UNGRADED)
    print(
        f"wf orchestra: {n_pass} pass / {n_needs} needs-finetune / "
        f"{n_ungraded} ungraded / {n_noevals} no-evals / {len(errored)} error "
        f"(model={args.model_name} quant={args.quant or 'unspecified'} grader={grader})"
    )
    if errored:
        names = ", ".join(r.name for r in errored)
        sys.stderr.write(
            f"wf orchestra: {len(errored)} skill(s) ERRORED on a real call — "
            f"FAILING (no fake passes). Skills: {names}. First error: {errored[0].error}\n"
        )
        return 2
    return 0


# ── selftest (STUB backend, NO network) ───────────────────────────────────────


# A unique sentinel the fixture writes into a referenced file; the stub echoes
# whatever it receives (see FILE_ECHO_STUB) so we can prove (A) injected the file.
FIXTURE_FILE_TOKEN = "INJECTED_FILE_CONTENT_MARKER_42"


def _write_fixture(root: Path) -> None:
    """Synthetic skills with evals in a tempdir, mirroring the real on-disk layout
    (<skill>/SKILL.md + <skill>/evals/evals.json). Engineered to cover: a GOOD
    answer passing and a BAD one failing; a NO-EVALS skill; (A) a skill whose eval
    references a `files` entry; (B) a skill whose expectations carry NO checkable
    tokens -> UNGRADED; (D) a skill with a tool-dependent prompt."""
    # Skill A: has evals with checkable backticked tokens.
    a = root / "stub-skill-good"
    (a / "evals").mkdir(parents=True)
    (a / "SKILL.md").write_text(
        "---\nname: stub-skill-good\ndescription: a stub skill for selftest\n---\n"
        "# Stub Skill Good\nAlways emit a `VERDICT` line and a `Rollback` section.\n",
        encoding="utf-8",
    )
    (a / "evals" / "evals.json").write_text(json.dumps({
        "skill_name": "stub-skill-good",
        "evals": [
            {
                "id": "good-1",
                "prompt": "STUB_CASE_GOOD: produce the verdict and rollback section.",
                "expected_output": "a VERDICT line and a Rollback section",
                "expectations": [
                    "The output contains a `VERDICT` line.",
                    "The output contains a `Rollback` section.",
                ],
            },
            {
                "id": "good-2",
                "prompt": "STUB_CASE_GOOD2: same requirement, structured assert.",
                "expected_output": "contains VERDICT and Rollback",
                "expectations": ["has the tokens"],
                "assert": {"contains": ["VERDICT", "Rollback"], "not_contains": ["FORBIDDEN"]},
            },
        ],
    }, indent=2), encoding="utf-8")

    # Skill B: NO evals (must classify NO-EVALS).
    b = root / "stub-skill-noevals"
    b.mkdir()
    (b / "SKILL.md").write_text(
        "---\nname: stub-skill-noevals\ndescription: no evals here\n---\n# No Evals\n",
        encoding="utf-8",
    )

    # (A) Skill with an eval that references a file. The file holds a unique token;
    # build_user_content must inject it under the FILE delimiter so the model sees
    # it. A file echoing stub then surfaces the token in its output.
    f = root / "stub-skill-files"
    (f / "evals" / "files").mkdir(parents=True)
    (f / "SKILL.md").write_text(
        "---\nname: stub-skill-files\ndescription: file-dependent eval\n---\n"
        "# Files\nUse the attached file.\n",
        encoding="utf-8",
    )
    (f / "evals" / "files" / "input.md").write_text(
        f"Repro details follow.\n{FIXTURE_FILE_TOKEN}\nend of file.\n",
        encoding="utf-8",
    )
    (f / "evals" / "evals.json").write_text(json.dumps({
        "skill_name": "stub-skill-files",
        "evals": [
            {
                "id": "files-1",
                "prompt": "STUB_CASE_FILES: analyze the attached file.",
                "expected_output": "the analysis references the file token",
                "files": ["evals/files/input.md"],
                # The expectation's checkable token is the injected file marker.
                "expectations": [
                    f"The output references the `{FIXTURE_FILE_TOKEN}` from the file.",
                ],
            },
        ],
    }, indent=2), encoding="utf-8")

    # (B) Skill whose expectations have NO checkable tokens (pure prose, no
    # backticks/quotes) and NO structured assert -> assertion grader yields None
    # for every case -> the skill classifies UNGRADED (not NEEDS-FINETUNE).
    u = root / "stub-skill-ungradeable"
    (u / "evals").mkdir(parents=True)
    (u / "SKILL.md").write_text(
        "---\nname: stub-skill-ungradeable\ndescription: prose-only expectations\n---\n"
        "# Ungradeable\nDo good work.\n",
        encoding="utf-8",
    )
    (u / "evals" / "evals.json").write_text(json.dumps({
        "skill_name": "stub-skill-ungradeable",
        "evals": [
            {
                "id": "ungradeable-1",
                "prompt": "STUB_CASE_UNGRADEABLE: respond thoughtfully.",
                "expected_output": "a thoughtful response",
                # Pure prose — no backticked/quoted literal to extract.
                "expectations": [
                    "The response should be thoughtful and well reasoned overall.",
                ],
            },
        ],
    }, indent=2), encoding="utf-8")

    # (D) Skill with a tool-dependent prompt (instructs the model to run a script
    # and copy a folder) -> is_tool_dependent True -> shows in the caveats section.
    t = root / "stub-skill-tooldep"
    (t / "evals").mkdir(parents=True)
    (t / "SKILL.md").write_text(
        "---\nname: stub-skill-tooldep\ndescription: tool-dependent eval\n---\n"
        "# Tool Dep\nRun the harness.\n",
        encoding="utf-8",
    )
    (t / "evals" / "evals.json").write_text(json.dumps({
        "skill_name": "stub-skill-tooldep",
        "evals": [
            {
                "id": "tooldep-1",
                "prompt": ("STUB_CASE_TOOLDEP: Run headless. Run "
                           "`python3 scripts/thing.py discover` and capture its "
                           "output, then COPY the run folder to scratch. "
                           "Emit a `VERDICT` line and a `Rollback` section."),
                "expected_output": "a VERDICT and Rollback",
                "expectations": [
                    "The output contains a `VERDICT` line.",
                    "The output contains a `Rollback` section.",
                ],
            },
        ],
    }, indent=2), encoding="utf-8")


def selftest() -> int:
    problems: list[str] = []

    with tempfile.TemporaryDirectory(prefix="orchestra-self-") as td:
        root = Path(td) / "skills"
        root.mkdir()
        _write_fixture(root)

        # Discovery.
        specs = discover_skills(skills_root=root)
        names = {s.name for s in specs}
        expected_names = {
            "stub-skill-good", "stub-skill-noevals", "stub-skill-files",
            "stub-skill-ungradeable", "stub-skill-tooldep",
        }
        if names != expected_names:
            problems.append(f"discovery wrong: {names}")
        # --skills accepts a comma-separated list of globs (selects exactly the named).
        filt = {s.name for s in discover_skills(
            skills_root=root, pattern="stub-skill-good, stub-skill-files")}
        if filt != {"stub-skill-good", "stub-skill-files"}:
            problems.append(f"comma-separated --skills filter wrong: {filt}")
        good_spec = next((s for s in specs if s.name == "stub-skill-good"), None)
        if good_spec is None or len(good_spec.evals) != 2:
            problems.append("stub-skill-good did not yield 2 evals")
        files_spec = next((s for s in specs if s.name == "stub-skill-files"), None)
        if files_spec is None or files_spec.skill_dir is None:
            problems.append("stub-skill-files spec/skill_dir missing")

        # ── (A) build_user_content injects the referenced file's contents. ──
        if files_spec is not None and files_spec.evals:
            uc = build_user_content(files_spec.evals[0], files_spec.skill_dir)
            if FIXTURE_FILE_TOKEN not in uc:
                problems.append(
                    "build_user_content did NOT inject the referenced file contents "
                    "(model would work blind on file-dependent evals)"
                )
            if "----- FILE: evals/files/input.md -----" not in uc:
                problems.append("build_user_content missing the FILE delimiter")
            # (A) a missing file injects a (MISSING) marker, never crashes.
            ev_missing = {"prompt": "p", "files": ["evals/files/does-not-exist.md"]}
            uc_missing = build_user_content(ev_missing, files_spec.skill_dir)
            if "(MISSING)" not in uc_missing:
                problems.append("build_user_content did not flag a missing file as (MISSING)")

        # ── GOOD stub: canned output satisfies the tokens -> PASS, no network. The
        #    file-echo stub also surfaces the injected file token for stub-skill-files. ──
        good_stub = StubBackend(responses={
            "STUB_CASE_GOOD": "Here is the result.\nVERDICT: PASS\n## Rollback\nsteps...",
            "STUB_CASE_FILES": (
                "Analyzing the file: I found " + FIXTURE_FILE_TOKEN +
                " in the attached content."
            ),
            "STUB_CASE_TOOLDEP": "VERDICT: PASS\n## Rollback\nsteps...",
        }, default="VERDICT: PASS\n## Rollback\nok")
        good_results = run_baseline(specs, good_stub, grader="assertion",
                                    threshold=DEFAULT_THRESHOLD)
        if good_stub.calls == []:
            problems.append("stub backend was never called (skills not driven)")
        gr = {r.name: r for r in good_results}
        if gr["stub-skill-good"].verdict != PASS:
            problems.append(
                f"good canned output did not PASS: verdict={gr['stub-skill-good'].verdict} "
                f"score={gr['stub-skill-good'].score}"
            )
        if gr["stub-skill-noevals"].verdict != NO_EVALS:
            problems.append("no-evals skill not classified NO-EVALS")

        # ── (A) file-dependent skill: with the file injected, the stub surfaced the
        #    token -> the case grades and PASSes. (Proves the file reached the model.) ──
        if gr["stub-skill-files"].verdict != PASS:
            problems.append(
                f"file-dependent skill did not PASS after injection: "
                f"verdict={gr['stub-skill-files'].verdict} score={gr['stub-skill-files'].score} "
                f"(file contents not reaching the model?)"
            )

        # ── (B) ungradeable skill: every case None -> verdict UNGRADED, NOT
        #    NEEDS-FINETUNE, score None, and counted as ungraded not graded. ──
        ung = gr["stub-skill-ungradeable"]
        if ung.verdict != UNGRADED:
            problems.append(
                f"ungradeable skill classified {ung.verdict}, expected UNGRADED "
                f"(must NOT be NEEDS-FINETUNE — there was no measurement to fail)"
            )
        if ung.verdict == NEEDS:
            problems.append("ungradeable skill wrongly classified NEEDS-FINETUNE (fake verdict)")
        if ung.score is not None:
            problems.append(f"ungradeable skill has a fabricated score {ung.score}, expected None")
        if ung.n_ungraded != 1 or ung.case_scores:
            problems.append(
                f"ungradeable skill bookkeeping wrong: n_ungraded={ung.n_ungraded} "
                f"graded={ung.case_scores}"
            )

        # ── (D) tool-dependent skill: cases flagged, still scored (not excluded). ──
        td = gr["stub-skill-tooldep"]
        if td.n_tool_dependent != 1 or td.tool_dependent_ids != ["tooldep-1"]:
            problems.append(
                f"tool-dependent case not flagged: n={td.n_tool_dependent} "
                f"ids={td.tool_dependent_ids}"
            )
        if not td.case_scores:
            problems.append("tool-dependent skill was excluded from scoring (it must NOT be)")

        # ── BAD stub: canned output MISSES the tokens -> NEEDS-FINETUNE. ──
        bad_stub = StubBackend(responses={}, default="I have no idea, sorry.")
        bad_results = run_baseline(specs, bad_stub, grader="assertion",
                                   threshold=DEFAULT_THRESHOLD)
        br = {r.name: r for r in bad_results}
        if br["stub-skill-good"].verdict != NEEDS:
            problems.append(
                f"planted BAD output was not classified NEEDS-FINETUNE: "
                f"verdict={br['stub-skill-good'].verdict} score={br['stub-skill-good'].score}"
            )
        if br["stub-skill-good"].score is not None and br["stub-skill-good"].score >= DEFAULT_THRESHOLD:
            problems.append("BAD output scored at/above threshold (grader is blind)")

        # (#22) the NEEDS-FINETUNE skill captured failure evidence (trace-as-gradient),
        # and the report surfaces it under the Failure-evidence section.
        if not br["stub-skill-good"].failure_evidence:
            problems.append("#22: NEEDS-FINETUNE skill did not capture any failure evidence")
        bad_report = render_report(
            bad_results, model_name="stub-qwen", model_url="stub://local",
            quant="q8_0", grader="assertion", threshold=DEFAULT_THRESHOLD, limit=None)
        if "Failure evidence (trace-as-gradient input for NEEDS-FINETUNE)" not in bad_report:
            problems.append("#22: report missing the Failure-evidence section for a NEEDS skill")

        # ── Grader unit: a GOOD output scores 1.0, a BAD output < threshold. ──
        ev = good_spec.evals[0] if good_spec else None
        if ev is not None:
            gscore, _, _ = grade_case(ev, "VERDICT: PASS\n## Rollback\nx", "assertion", None)
            if gscore != 1.0:
                problems.append(f"assertion grader: good output scored {gscore}, expected 1.0")
            bscore, _, _ = grade_case(ev, "nothing relevant here", "assertion", None)
            if bscore >= DEFAULT_THRESHOLD:
                problems.append(f"assertion grader: bad output scored {bscore} >= threshold")

        # ── Structured assert: not_contains must FAIL on a forbidden token. ──
        if good_spec is not None:
            assert_ev = good_spec.evals[1]
            s_ok, _ = assertion_grade(assert_ev, "VERDICT here and a Rollback")
            if s_ok != 1.0:
                problems.append(f"assert-block good output scored {s_ok}, expected 1.0")
            s_bad, _ = assertion_grade(assert_ev, "VERDICT Rollback FORBIDDEN")
            if s_bad is None or s_bad >= 1.0:
                problems.append("assert-block did not penalize a not_contains violation")

        # ── (B) grade_case returns None (not 0.0) for an uncheckable case. ──
        if ung is not None and ung.spec.evals:
            none_score, used, _ = grade_case(ung.spec.evals[0], "anything",
                                             "assertion", None)
            if none_score is not None:
                problems.append(
                    f"grade_case fabricated a score {none_score} for an uncheckable "
                    f"case; expected None (used={used})"
                )

        # ── (D) is_tool_dependent unit: only a backticked command/script fires;
        #    benign 'run headless' prose and plain prose do NOT. ──
        if not is_tool_dependent("Run `python3 foo.py` and capture its output"):
            problems.append("is_tool_dependent missed an obvious backticked script invocation")
        if is_tool_dependent("Run headless and capture its output."):
            problems.append("is_tool_dependent over-flagged the benign 'run headless' directive")
        if is_tool_dependent("Summarize the runbook for the on-call engineer."):
            problems.append("is_tool_dependent false-positived on plain prose mentioning 'run'")

        # ── ERROR path: a backend that raises is recorded as ERROR, never PASS. ──
        class _BoomBackend(Backend):
            def chat(self, system: str, user: str) -> str:
                raise BackendError("simulated unreachable endpoint")

        boom_results = run_baseline(specs, _BoomBackend(), grader="assertion",
                                    threshold=DEFAULT_THRESHOLD)
        boom = {r.name: r for r in boom_results}
        if boom["stub-skill-good"].verdict != ERROR:
            problems.append("a raising backend was not recorded as ERROR")
        if boom["stub-skill-good"].verdict == PASS:
            problems.append("a raising backend produced a PASS (fake pass — fatal)")

        # ── Report is produced and records model + quant prominently, no fabrication.
        #    It must also surface UNGRADED and the (D) tool-dependent caveats. ──
        report = render_report(
            good_results, model_name="stub-qwen", model_url="stub://local",
            quant="q8_0", grader="assertion", threshold=DEFAULT_THRESHOLD, limit=None,
        )
        for needle in ("stub-qwen", "q8_0", "PASS", "NO-EVALS", "By skill family",
                       "Per-skill", "Totals", "UNGRADED",
                       "## Caveats — tool-dependent evals (not single-shot measurable)",
                       "stub-skill-tooldep", "tooldep-1"):
            if needle not in report:
                problems.append(f"report missing expected content: {needle!r}")

        # ── (D) caveats section says "none" when no tool-dependent evals exist. ──
        no_tool_results = [r for r in good_results if r.name != "stub-skill-tooldep"]
        report_no_tool = render_report(
            no_tool_results, model_name="stub-qwen", model_url="stub://local",
            quant="q8_0", grader="assertion", threshold=DEFAULT_THRESHOLD, limit=None,
        )
        caveat_idx = report_no_tool.find(
            "## Caveats — tool-dependent evals (not single-shot measurable)")
        if caveat_idx < 0 or "none" not in report_no_tool[caveat_idx:]:
            problems.append("caveats section did not state 'none' when no tool-dependent evals")

    # ── No-network proof: OpenAIChatBackend against a dead port raises BackendError
    #    (it does NOT silently return a fake answer). Uses an unroutable test addr;
    #    short timeout so the selftest stays fast and never reaches the network.
    dead = OpenAIChatBackend("http://127.0.0.1:1/v1", "nobody", timeout=1)
    raised = False
    try:
        dead.chat("x", "y")
    except BackendError:
        raised = True
    except Exception as exc:  # noqa: BLE001
        problems.append(f"dead-endpoint call raised non-BackendError: {exc!r}")
        raised = True
    if not raised:
        problems.append("dead-endpoint call did NOT fail loud (silent fake answer risk)")

    # ── (E) Judge verdict parser — guards the MEASUREMENT INSTRUMENT. A malformed or
    #    truncated judge response (unescaped quote in `notes`, no closing brace) must
    #    RECOVER the numeric verdict rather than drop a real grade to ERROR (a dropped
    #    verdict silently corrupts the baseline). A chatty-but-valid response still
    #    parses normally (the fallback must NOT hijack a good parse), and a response
    #    with no verdict still fails CLOSED (never a fabricated grade). ──
    broken = (
        '{"passed": 4, "total": 5, "notes": "Code: 2h -> 7200, '
        '"1h2m3s" -> 3723, ValueError for empty, no closing brace'
    )
    try:
        v = _extract_json_verdict(broken)
        if (int(v["passed"]), int(v["total"])) != (4, 5):
            problems.append(f"verdict-recovery returned wrong numbers: {v}")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"verdict-recovery dropped a PRESENT verdict to ERROR: {exc!r}")
    chatty = 'Reasoning...\n```json\n{"passed": 5, "total": 5, "notes": "all ok"}\n```'
    cv = _extract_json_verdict(chatty)
    if (int(cv["passed"]), int(cv["total"]), cv.get("notes")) != (5, 5, "all ok"):
        problems.append(f"chatty valid verdict mis-parsed (fallback hijacked a good parse?): {cv}")
    try:
        _extract_json_verdict("the model seemed fine to me")
        problems.append("verdict parser did NOT fail closed on a response carrying no verdict")
    except ValueError:
        pass

    class _MalformedJudge(Backend):
        def chat(self, system: str, user: str) -> str:
            return broken

    jscore, _ = judge_grade({"expectations": ["x"]}, "out", _MalformedJudge())
    if abs(jscore - 0.8) > 1e-9:
        problems.append(f"judge_grade did not recover 4/5 (0.8) from malformed JSON: {jscore}")

    # ── (F) Multi-turn eval mode ───────────────────────────────────────────────
    # All assertions are stub-based, NO network.
    # 1. A 2-turn conversation accumulates transcript correctly.
    # 2. Mock tool dispatch: model emits TOOL_CALL -> canned response injected,
    #    call recorded.
    # 3. assert_tool_calls PASSES on a good transcript (right tool called).
    # 4. assert_tool_calls FAILS on a bad transcript (wrong / no tool called).
    # 5. Malformed TOOL_CALL JSON fails closed (grading failure, not silent pass).
    # 6. BackendError in multi-turn = ERROR, never PASS.

    # ── (F.1) _parse_tool_call unit tests ──────────────────────────────────────
    # _parse_tool_call returns a ToolCallRecord or None.
    # Good call: returns ToolCallRecord with tool_name set.
    tc_good = _parse_tool_call(
        'Some text\nTOOL_CALL: {"tool": "write_file", "args": {"path": "x.md"}}'
    )
    if tc_good is None or tc_good.tool_name != "write_file":
        problems.append(
            f"_parse_tool_call failed to extract a valid tool call: {tc_good}"
        )
    if tc_good is not None and tc_good.args.get("path") != "x.md":
        problems.append(
            f"_parse_tool_call did not capture args correctly: {tc_good.args}"
        )
    # No call — plain text returns None.
    tc_none = _parse_tool_call("I will now think about this carefully.")
    if tc_none is not None:
        problems.append(
            f"_parse_tool_call returned non-None on a plain text response: {tc_none}"
        )
    # Malformed JSON -> ToolCallRecord(tool_name='__malformed__') — fail closed.
    # The __malformed__ sentinel means the grader can record this as a failure,
    # rather than silently treating it as "no call" (which would hide the error).
    tc_bad = _parse_tool_call("TOOL_CALL: {not valid json!!}")
    if tc_bad is None or tc_bad.tool_name != "__malformed__":
        problems.append(
            f"_parse_tool_call did not return __malformed__ sentinel on bad JSON: "
            f"got {tc_bad} (fail-closed violated — malformed must never silently pass)"
        )

    # ── (F.2) run_multiturn + transcript accumulation ──────────────────────────
    mt_ev = {
        "id": "mt-selftest",
        "mode": "multi-turn",
        "prompt": "Selftest multi-turn eval: save then load.",
        "conversation": [
            {"role": "user", "content": "Save state: agent=saga, status=complete"},
            {"role": "user", "content": "Load the saga state back"},
        ],
        "tools": {
            "write_file": {"response": "saved progress/saga.md"},
            "read_file":  {"response": "agent=saga, status=complete"},
        },
        "assert_tool_calls": [
            {"turn": 0, "tool": "write_file"},
            {"turn": 1, "tool": "read_file"},
        ],
        "expected_output": "Model saves then loads state via file tools.",
        "expectations": [
            "Model calls `write_file` in turn 1",
            "Model calls `read_file` in turn 2",
            "Model reports the loaded `saga` state back",
        ],
    }

    # Stub backend that emits correct TOOL_CALLs at the right turns.
    mt_good_stub = StubBackend(
        responses={},
        default="",
        mt_responses={
            (0, "Save state"): (
                'I will save the state now.\n'
                'TOOL_CALL: {"tool": "write_file", "args": {"path": "progress/saga.md", '
                '"content": "agent=saga, status=complete"}}\n'
            ),
            (1, "Load the saga"): (
                'I will load the state now.\n'
                'TOOL_CALL: {"tool": "read_file", "args": {"path": "progress/saga.md"}}\n'
                'The saga state is: agent=saga, status=complete'
            ),
        },
    )
    system_mt = "You are a WDS memory agent. Save and load state using TOOL_CALL."
    transcript_good, tool_calls_good = run_multiturn(
        system_mt, mt_ev, mt_good_stub, mt_ev["tools"]
    )

    # Transcript must include both user turns and both assistant turns.
    user_turns = [m for m in transcript_good if m["role"] == "user"]
    asst_turns = [m for m in transcript_good if m["role"] == "assistant"]
    tool_result_turns = [m for m in transcript_good if m["role"] == "tool_result"]
    if len(user_turns) != 2:
        problems.append(
            f"multi-turn transcript: expected 2 user turns, got {len(user_turns)}"
        )
    if len(asst_turns) != 2:
        problems.append(
            f"multi-turn transcript: expected 2 assistant turns, got {len(asst_turns)}"
        )
    if len(tool_result_turns) != 2:
        problems.append(
            f"multi-turn transcript: expected 2 tool_result turns (one per tool call), "
            f"got {len(tool_result_turns)}"
        )

    # Tool calls recorded correctly.
    if len(tool_calls_good) != 2:
        problems.append(
            f"multi-turn: expected 2 tool_calls_recorded, got {len(tool_calls_good)}"
        )
    if tool_calls_good and tool_calls_good[0].tool_name != "write_file":
        problems.append(
            f"multi-turn: turn 0 expected write_file, got {tool_calls_good[0].tool_name}"
        )
    if len(tool_calls_good) > 1 and tool_calls_good[1].tool_name != "read_file":
        problems.append(
            f"multi-turn: turn 1 expected read_file, got {tool_calls_good[1].tool_name}"
        )

    # Tool result was injected into the transcript.
    if tool_result_turns and "saved progress/saga.md" not in tool_result_turns[0]["content"]:
        problems.append(
            "multi-turn: write_file canned response not injected into transcript"
        )

    # ── (F.3) grade_multiturn PASSES on good transcript ────────────────────────
    score_good, grader_used_good, ev_good = grade_multiturn(
        mt_ev, transcript_good, tool_calls_good, "assertion", None
    )
    if score_good is None or score_good < DEFAULT_THRESHOLD:
        problems.append(
            f"grade_multiturn: good transcript scored {score_good} (expected >= "
            f"{DEFAULT_THRESHOLD}); grader={grader_used_good}; evidence={ev_good}"
        )

    # ── (F.4) grade_multiturn FAILS on bad transcript (no tool calls) ──────────
    # A stub that emits plain text with no TOOL_CALL at either turn.
    mt_bad_stub = StubBackend(
        responses={},
        default="I will think about this and respond in prose with no tool call.",
    )
    mt_bad_stub.mt_call_count = 0  # reset
    transcript_bad, tool_calls_bad = run_multiturn(
        system_mt, mt_ev, mt_bad_stub, mt_ev["tools"]
    )
    if tool_calls_bad:
        problems.append(
            f"multi-turn bad stub: expected no tool calls, got {tool_calls_bad}"
        )
    score_bad, grader_used_bad, ev_bad = grade_multiturn(
        mt_ev, transcript_bad, tool_calls_bad, "assertion", None
    )
    if score_bad is not None and score_bad >= DEFAULT_THRESHOLD:
        problems.append(
            f"grade_multiturn: bad transcript (no tool calls) scored {score_bad} >= "
            f"{DEFAULT_THRESHOLD} — should FAIL when required tool calls are missed"
        )
    # phase1 failure must cap score at <= 0.5
    if score_bad is not None and score_bad > 0.5:
        problems.append(
            f"grade_multiturn: missed tool calls did not cap score at 0.5; got {score_bad}"
        )

    # ── (F.5) Malformed TOOL_CALL fails closed ──────────────────────────────────
    # A malformed TOOL_CALL JSON is treated as "no tool call emitted" by
    # _parse_tool_call (returns None). The tool_calls list is empty, so
    # assert_tool_calls assertions score 0.0 for each missed call.
    # The grade must fall below threshold -- it must NOT silently pass.
    mt_malformed_stub = StubBackend(
        responses={},
        default="",
        mt_responses={
            (0, "Save state"): "TOOL_CALL: {not valid json!!}",
            (1, "Load the saga"): "Prose response, no tool call.",
        },
    )
    transcript_mal, tool_calls_mal = run_multiturn(
        system_mt, mt_ev, mt_malformed_stub, mt_ev["tools"]
    )
    # Malformed JSON -> _parse_tool_call returns __malformed__ sentinel -> recorded.
    # The sentinel MUST be recorded (not silently dropped) so the grader can fail it.
    if not any(tc.tool_name == "__malformed__" for tc in tool_calls_mal):
        problems.append(
            "multi-turn (F.5): malformed TOOL_CALL JSON was NOT recorded as "
            "__malformed__ sentinel in tool_calls (silently vanished — fail-closed violated). "
            f"tool_calls_mal={tool_calls_mal}"
        )
    # Grade must fail: assert_tool_calls expects write_file at turn 0, but only
    # __malformed__ was recorded there. Score must be below threshold.
    score_mal, _, ev_mal = grade_multiturn(
        mt_ev, transcript_mal, tool_calls_mal, "assertion", None
    )
    if score_mal is not None and score_mal >= DEFAULT_THRESHOLD:
        problems.append(
            f"grade_multiturn (F.5): malformed tool call produced score {score_mal} >= "
            f"{DEFAULT_THRESHOLD} (should fail closed, not silently pass)"
        )

    # ── (F.6) BackendError in multi-turn = ERROR, never PASS ────────────────────
    # Use run_baseline with a skill that has a multi-turn eval and a raising backend.
    with tempfile.TemporaryDirectory(prefix="orchestra-mt-boom-") as td_boom:
        root_boom = Path(td_boom) / "skills"
        root_boom.mkdir()
        sk_boom = root_boom / "mt-boom-skill"
        (sk_boom / "evals").mkdir(parents=True)
        (sk_boom / "SKILL.md").write_text(
            "---\nname: mt-boom-skill\ndescription: boom\n---\n# Boom\n",
            encoding="utf-8",
        )
        (sk_boom / "evals" / "evals.json").write_text(json.dumps({
            "skill_name": "mt-boom-skill",
            "evals": [{
                "id": "mt-boom-1",
                "mode": "multi-turn",
                "prompt": "A multi-turn eval that errors on the backend.",
                "conversation": [{"role": "user", "content": "Do something"}],
                "tools": {},
                "assert_tool_calls": [],
                "expected_output": "anything",
                "expectations": [],
            }],
        }, indent=2), encoding="utf-8")

        class _MTBoomBackend(Backend):
            def chat_messages(self, messages: list[dict]) -> str:
                raise BackendError("simulated multi-turn backend failure")

        boom_specs = discover_skills(skills_root=root_boom)
        boom_mt_results = run_baseline(boom_specs, _MTBoomBackend(),
                                       grader="assertion",
                                       threshold=DEFAULT_THRESHOLD)
        boom_mt = {r.name: r for r in boom_mt_results}
        if boom_mt.get("mt-boom-skill", None) is None:
            problems.append("multi-turn BackendError test: skill not discovered")
        elif boom_mt["mt-boom-skill"].verdict != ERROR:
            problems.append(
                f"multi-turn BackendError: expected ERROR verdict, got "
                f"{boom_mt['mt-boom-skill'].verdict} (backend error must never produce PASS)"
            )
        elif boom_mt["mt-boom-skill"].verdict == PASS:
            problems.append(
                "multi-turn BackendError produced PASS — fatal honesty violation"
            )

    # ── (F.7) phase1-only HARD GATE: a missed required tool call must fail closed
    #    even when the passed fraction (4/5 = 0.80) would otherwise clear the bar. ──
    mt_gate_ev = {
        "assert_tool_calls": [{"turn": i, "tool": f"t{i}"} for i in range(5)],
        "expectations": [],  # no phase-2 grade -> tool-calls-only branch
    }
    mt_gate_calls = [ToolCallRecord(turn_index=i, tool_name=f"t{i}", args={})
                     for i in range(4)]  # t4 (turn 4) is MISSED
    gate_score, _gate_used, _ = grade_multiturn(
        mt_gate_ev, [], mt_gate_calls, "assertion", None)
    if gate_score is None or gate_score >= DEFAULT_THRESHOLD:
        problems.append(
            f"multi-turn (F.7): tool-calls-only with 4/5 required calls scored "
            f"{gate_score} (>= {DEFAULT_THRESHOLD}); a missed required tool call must "
            f"fail closed (<= 0.5) in every branch"
        )

    # ── (#8) Verdict STABILITY band: _stability flags a verdict whose 1σ CI
    #    straddles the threshold; confidently-above / confidently-below do NOT. ──
    if _stability([1.0, 1.0, 1.0, 1.0], DEFAULT_THRESHOLD)[2]:
        problems.append("stability: an all-1.0 skill was wrongly flagged UNSTABLE")
    if _stability([0.0, 0.0, 0.0, 0.0], DEFAULT_THRESHOLD)[2]:
        problems.append("stability: an all-0.0 skill was wrongly flagged UNSTABLE")
    if not _stability([1.0, 1.0, 1.0, 0.0], DEFAULT_THRESHOLD)[2]:
        problems.append("stability: a 3/4 (mean 0.75, near 0.80) skill should be UNSTABLE")
    if not _stability([0.85], DEFAULT_THRESHOLD)[2]:
        problems.append("stability: a lone case 0.05 from the threshold should be UNSTABLE")
    if _stability([], DEFAULT_THRESHOLD)[2]:
        problems.append("stability: an empty score list must not be UNSTABLE")
    # the report surfaces the UNSTABLE totals label (report built earlier).
    if "UNSTABLE" not in report:
        problems.append("report missing the UNSTABLE totals label")

    if problems:
        print("wf orchestra selftest: FAIL")
        for p in problems:
            print("  - " + p)
        return 1
    print(
        "wf orchestra selftest: PASS (stub backend drives discovered skills with NO "
        "network; assertion grader passes a good canned output and fails a planted bad "
        "one; structured assert penalizes not_contains; NO-EVALS classified; a raising "
        "backend is recorded ERROR not PASS; report records model+quant; a dead OpenAI "
        "endpoint fails loud — no fake pass; (A) eval `files` are injected into the user "
        "prompt under a delimiter, missing files flagged not fatal; (B) an uncheckable "
        "case scores None, is excluded from the mean, and an all-uncheckable skill is "
        "UNGRADED not NEEDS-FINETUNE; (D) tool-dependent evals are flagged in the report "
        "caveats section, still scored; (E) a malformed/truncated judge verdict is "
        "recovered (passed/total) instead of dropped to ERROR, a valid chatty verdict "
        "still parses, and a verdict-less judge response fails closed; (F) multi-turn "
        "eval mode: transcript accumulates correctly across turns, mock tool dispatch "
        "injects TOOL_RESULT canned responses and records calls, assert_tool_calls passes "
        "on good transcript and fails on bad, malformed TOOL_CALL JSON fails closed "
        "(recorded as __malformed__ sentinel, assertion fails for any assert requiring that turn), "
        "BackendError in multi-turn = ERROR never PASS); (#8) a PASS/NEEDS verdict whose 1σ CI "
        "straddles the threshold is flagged UNSTABLE (confidently-above/below are not); "
        "(#22) a NEEDS-FINETUNE skill captures sub-threshold eval evidence and the report "
        "surfaces it as the trace-as-gradient input"
    )
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="wf orchestra",
        description="Model-agnostic measurement baseline harness (specialist orchestra §3).",
    )
    # Top-level --selftest works without a subcommand (mirrors scaffold/deploy).
    ap.add_argument("--selftest", action="store_true", help="run built-in self-test (stub backend, no network)")
    sub = ap.add_subparsers(dest="cmd")

    p_base = sub.add_parser("baseline", help="score a target model against skills' evals")
    p_base.add_argument("--model", help="OpenAI-compatible base URL, e.g. http://localhost:11434/v1")
    p_base.add_argument("--model-name", help="model id to send in the request (e.g. qwen2.5:7b)")
    p_base.add_argument("--quant", help="quantization label to record in the report (e.g. q8_0)")
    p_base.add_argument("--grader", default=DEFAULT_GRADER, choices=VALID_GRADERS,
                        help=f"grading policy (default: {DEFAULT_GRADER})")
    p_base.add_argument("--judge-model", help="OpenAI-compatible base URL for the judge model (judge/hybrid)")
    p_base.add_argument("--judge-model-name", help="judge model id (defaults to --model-name)")
    p_base.add_argument("--skills", help="glob to filter skill names (e.g. 'bmad-*')")
    p_base.add_argument("--limit", type=int, help="max eval cases per skill")
    p_base.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"pass threshold on mean case score (default: {DEFAULT_THRESHOLD})")
    p_base.add_argument("--out", help="write the Markdown report to this path (else stdout)")

    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if args.cmd == "baseline":
        if not args.model:
            ap.error("baseline requires --model <url>")
        if not args.model_name:
            ap.error("baseline requires --model-name <name>")
        return cmd_baseline(args)

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
