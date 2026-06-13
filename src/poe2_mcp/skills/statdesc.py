"""
Render PoB2 stat ids into the in-game English line they describe.

PoB2 ships the descriptions GGG uses for tooltips as machine-generated Lua tables
under src/Data/StatDescriptions/. Each entry maps one or more stat ids to a set
of conditional variants; the right variant is chosen by per-stat value gates
("limits"), and its `text` is a template with {0}, {1}, … placeholders. Rendering
that template turns a raw id+value — `{"id": "base_reduce_enemy_fire_resistance_%",
"value": 30}` — into the line a player reads: "Penetrate 30% Fire Resistance".

Two halves live here:

  * build time — parse_stat_descriptions() turns the .lua into a slim, JSON-able
    map of {stat_id: [variant, ...]}. scripts/build_stat_data.py vendors it,
    intersected against the ids the gem db actually uses.
  * run time — render() picks the matching variant for a value and substitutes
    the placeholders. No Lua, no I/O; GemData calls it to attach `text`.

Phase 1 scope (see docs/plain-english-stat-text.md): SINGLE-stat lines only —
the bulk of support/flat-effect lines, which is what drives gem advice. Multi-stat
lines (e.g. a min+max damage pair sharing one line) are skipped here and fall back
to the raw id; value transforms (ms→s, ÷100) are not applied — the raw number is
rendered. The template wording itself ("more" vs "increased" vs "Penetrate")
already resolves the _final-vs-_+% trap for free.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .._resources import resource_path

# ---------------------------------------------------------------------------
# Build time: parse the PoB2 stat-description Lua into a slim map.
# ---------------------------------------------------------------------------


class _LuaTableParser:
    """A recursive-descent parser for the subset of Lua the description files use:
    nested tables of integer/string/bareword-keyed entries whose values are
    numbers, double-quoted strings (the `#` wildcard is just the string "#"), and
    further tables. The files are machine-generated and regular, so this handles
    them without a full Lua interpreter."""

    _TOKEN = re.compile(
        r"""
          (?P<ws>\s+)
        | (?P<comment>--[^\n]*)
        | (?P<string>"(?:[^"\\]|\\.)*")
        | (?P<number>-?\d+(?:\.\d+)?)
        | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
        | (?P<punct>[\{\}\[\]=,])
        """,
        re.VERBOSE,
    )

    def __init__(self, text: str):
        self._toks = [
            (m.lastgroup, m.group())
            for m in self._TOKEN.finditer(text)
            if m.lastgroup not in ("ws", "comment")
        ]
        self._i = 0

    def _peek(self):
        return self._toks[self._i] if self._i < len(self._toks) else (None, None)

    def _next(self):
        tok = self._toks[self._i]
        self._i += 1
        return tok

    def parse_return(self):
        """Consume an optional leading `return` and parse the top-level table."""
        kind, val = self._peek()
        if kind == "name" and val == "return":
            self._next()
        return self._value()

    def _value(self):
        kind, val = self._peek()
        if kind == "punct" and val == "{":
            return self._table()
        if kind == "string":
            self._next()
            return _unescape(val[1:-1])
        if kind == "number":
            self._next()
            return float(val) if "." in val else int(val)
        if kind == "name":  # bare true/false/nil
            self._next()
            return {"true": True, "false": False, "nil": None}.get(val, val)
        raise ValueError(f"unexpected token {kind}={val!r}")

    def _table(self):
        """Parse `{ ... }` into a dict. Positional entries get 1-based integer keys,
        matching Lua array semantics, so [1]=… explicit keys and bare values mix
        cleanly."""
        self._next()  # '{'
        out: dict = {}
        pos = 1
        while True:
            kind, val = self._peek()
            if kind == "punct" and val == "}":
                self._next()
                return out
            if kind == "punct" and val == "[":
                self._next()
                k = self._value()
                self._expect("]")
                self._expect("=")
                out[k] = self._value()
            elif kind == "name" and self._toks[self._i + 1][1] == "=":
                self._next()  # name
                self._next()  # '='
                out[val] = self._value()
            else:
                out[pos] = self._value()
                pos += 1
            kind, val = self._peek()
            if kind == "punct" and val == ",":
                self._next()

    def _expect(self, punct: str):
        kind, val = self._next()
        if not (kind == "punct" and val == punct):
            raise ValueError(f"expected {punct!r}, got {val!r}")


_ESCAPES = {"n": " ", "t": " ", '"': '"', "\\": "\\"}


def _unescape(s: str) -> str:
    r"""Resolve Lua string escapes and normalise whitespace. \n / \t become spaces
    (the source wraps long tooltip lines with literal newlines we don't want in
    JSON output), then runs of whitespace collapse to one. Stat ids have no
    whitespace, so this is a no-op for them."""
    s = re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), s)
    return re.sub(r"\s+", " ", s).strip()


def _int_keys(d: dict) -> list:
    """Values of d at integer keys, in numeric order (Lua array part)."""
    return [d[k] for k in sorted(k for k in d if isinstance(k, int))]


def _norm_bound(b):
    """A limit bound: the wildcard "#" means unbounded -> None; else a number."""
    return None if b == "#" else b


def _collect_variants(block) -> list[dict]:
    """Flatten an entry's descriptor block into an ordered list of variants, each
    {limits: [[lo,hi], ...], text: str}. The block nests a level deeper than the
    {limit,text} leaves, so descend until we hit dicts carrying a `text`."""
    out: list[dict] = []

    def walk(node):
        if not isinstance(node, dict):
            return
        if "text" in node:
            limit = node.get("limit") or {}
            limits = [
                [_norm_bound(pair.get(1)), _norm_bound(pair.get(2))]
                for pair in _int_keys(limit)
            ]
            out.append({"limits": limits, "text": node["text"]})
            return
        for child in _int_keys(node):
            walk(child)

    walk(block)
    return out


def parse_stat_descriptions(text: str, single_stat_only: bool = True) -> dict[str, list[dict]]:
    """Parse a PoB2 stat-description .lua into {stat_id: [variant, ...]}.

    Each variant is {limits, text}; for single-stat entries (the Phase-1 scope)
    limits has exactly one [lo, hi] pair, the gate on that stat's value. Entries
    keyed by more than one stat id are skipped when single_stat_only (default),
    since rendering them needs sibling values we don't have in isolation.
    """
    root = _LuaTableParser(text).parse_return()
    out: dict[str, list[dict]] = {}
    for entry in _int_keys(root):
        if not isinstance(entry, dict):
            continue
        stats = _int_keys(entry.get("stats", {}))
        if not stats or (single_stat_only and len(stats) != 1):
            continue
        variants = [v for v in _collect_variants(entry) if v["text"]]
        if not variants:
            continue
        # First entry wins per id (the gem-scope file is the primary source).
        out.setdefault(stats[0], variants)
    return out


# ---------------------------------------------------------------------------
# Run time: render a value against the vendored variants.
# ---------------------------------------------------------------------------

# {0}, {1:+d}, … — a placeholder index with an optional format spec.
_PLACEHOLDER = re.compile(r"\{(\d+)(?::([^}]+))?\}")


def _matches(limits: list, value) -> bool:
    """True if value satisfies the single limit pair for a single-stat variant.
    A missing/empty limit (no gate) always matches. A non-numeric bound (PoB's
    rare `!` negation sentinel) can't be evaluated here, so the variant is skipped
    and rendering falls through to the next one."""
    if not limits:
        return True
    lo, hi = limits[0]
    if lo is not None:
        if not isinstance(lo, (int, float)) or value < lo:
            return False
    if hi is not None:
        if not isinstance(hi, (int, float)) or value > hi:
            return False
    return True


def _fmt_number(value, spec: str | None) -> str:
    """Format a value for substitution. Phase 1 honours only the sign-forcing
    spec (`+d`/`+`); everything else renders the raw number, trimming a trailing
    `.0` so ints read cleanly."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if spec and spec.startswith("+"):
        return f"{value:+}"
    return str(value)


def render(variants: list[dict], value, display=None) -> str | None:
    """Render the in-game line for a single-stat value, or None if no variant's
    limit matches. Picks the first matching variant (limits are ordered most- to
    least-specific in the source) and substitutes its placeholders.

    `value` is matched against the limits; `display` (defaulting to `value`) is
    what's substituted — they differ when a unit transform applies (e.g. a
    millisecond stat matches on its raw value but displays the seconds figure)."""
    if not variants:
        return None
    if display is None:
        display = value
    for v in variants:
        if _matches(v.get("limits") or [], value):
            return _PLACEHOLDER.sub(
                lambda m: _fmt_number(display, m.group(2)), v["text"]
            )
    return None


def _display_value(stat_id: str, value):
    """Convert a raw stat value to the figure the tooltip shows. Phase 1 handles
    the one clean, common unit transform: millisecond stats (`*_ms`) render in
    seconds. Other transforms (per-minute rates, ÷100 fractions) are Phase 2 and
    render raw for now."""
    if isinstance(value, (int, float)) and stat_id.endswith("_ms"):
        return value / 1000
    return value


class StatDescriptions:
    """The vendored stat-id → in-game-line map, scoped by support vs. active skill.

    Wording differs by scope: a support's lines read "Supported Skills deal …"
    (the `support` scope, from PoB2's gem_stat_descriptions), while an active
    skill's own stats read plain "… increased …" (the `skill` scope). text()
    tries the scope that matches the gem first, then the other as a fallback —
    so a line still renders if it only exists in the other scope."""

    def __init__(self, support: dict[str, list[dict]], skill: dict[str, list[dict]],
                 meta: dict | None = None):
        self._support = support
        self._skill = skill
        self.meta = meta or {}

    def text(self, stat_id: str, value, is_support: bool) -> str | None:
        """The rendered line for one stat id+value, or None if there's no single-
        stat description for it (internal/no-display stats, and the multi-stat
        lines Phase 1 doesn't render, both return None and keep the raw id)."""
        # Boolean flag-stats ("Cannot be Frozen") carry no number; match the
        # no-gate variant with a neutral 1 so the placeholder-free text renders.
        v = 1 if value is True else value
        if not isinstance(v, (int, float)):
            return None
        primary, secondary = (
            (self._support, self._skill) if is_support else (self._skill, self._support)
        )
        for scope in (primary, secondary):
            variants = scope.get(stat_id)
            if variants:
                line = render(variants, v, _display_value(stat_id, v))
                if line:
                    return line
        return None


def load_stat_descriptions(path: str | Path) -> StatDescriptions:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    scopes = data.get("scopes", {})
    return StatDescriptions(scopes.get("support", {}), scopes.get("skill", {}),
                            data.get("meta", {}))


def load_default_stat_descriptions() -> StatDescriptions | None:
    """Load the vendored descriptions, or None if the file isn't present (the
    server then simply omits rendered text and keeps the raw ids)."""
    env_path = os.environ.get("STAT_DESC_PATH")
    path = Path(env_path) if env_path else resource_path("data", "poe2_stat_descriptions.json")
    if not path.exists():
        return None
    return load_stat_descriptions(path)
