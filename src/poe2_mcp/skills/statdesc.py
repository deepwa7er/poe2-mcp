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
    {limits: [[lo,hi], ...], text: str, transforms?: {placeholder: [handler, arg]}}.
    The block nests a level deeper than the {limit,text} leaves, so descend until we
    hit dicts carrying a `text`; that leaf's own integer children are the per-
    placeholder value transforms (e.g. {"1": ["milliseconds_to_seconds", 1]})."""
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
            # Integer-keyed children of a text leaf are {k=handler, v=arg} transform
            # specs, one per 1-based placeholder index.
            transforms = {
                str(ik): [node[ik]["k"], node[ik].get("v")]
                for ik in node
                if isinstance(ik, int) and isinstance(node[ik], dict) and "k" in node[ik]
            }
            v = {"limits": limits, "text": node["text"]}
            if transforms:
                v["transforms"] = transforms
            out.append(v)
            return
        for child in _int_keys(node):
            walk(child)

    walk(block)
    return out


def parse_stat_descriptions(text: str) -> dict:
    """Parse a PoB2 stat-description .lua into {"single": {...}, "multi": [...]}.

    `single` maps a stat id to its variants (each {limits, text, transforms?}); these
    render from one id+value. `multi` is a list of {stats, variants} entries keyed by
    several stat ids (e.g. min+max damage on one line) — they render only when all the
    sibling values are present, so the runtime keys them by member id and renders the
    line once. First single entry wins per id (gem scope is the primary source)."""
    root = _LuaTableParser(text).parse_return()
    single: dict[str, list[dict]] = {}
    multi: list[dict] = []
    for entry in _int_keys(root):
        if not isinstance(entry, dict):
            continue
        stats = _int_keys(entry.get("stats", {}))
        variants = [v for v in _collect_variants(entry) if v["text"]]
        if not stats or not variants:
            continue
        if len(stats) == 1:
            single.setdefault(stats[0], variants)
        else:
            multi.append({"stats": stats, "variants": variants})
    return {"single": single, "multi": multi}


# ---------------------------------------------------------------------------
# Run time: render a value against the vendored variants.
# ---------------------------------------------------------------------------

# {0}, {1:+d}, … — a placeholder index with an optional format spec.
_PLACEHOLDER = re.compile(r"\{(\d+)(?::([^}]+))?\}")

# Gem quality caps at 20% in PoE2; a quality_stats value is per 1% of quality, so
# its effect at the cap is value * 20. The suffix flags that scaling in the line.
_MAX_QUALITY = 20
_QUALITY_SUFFIX = " (at 20% quality)"


def _limit_ok(pair, value) -> bool:
    """True if value satisfies one [lo, hi] limit pair. A missing pair (no gate)
    always matches. A non-numeric bound (PoB's rare `!` negation sentinel) can't be
    evaluated, so it fails and rendering falls through to the next variant."""
    if not pair:
        return True
    lo, hi = pair
    if lo is not None and (not isinstance(lo, (int, float)) or value < lo):
        return False
    if hi is not None and (not isinstance(hi, (int, float)) or value > hi):
        return False
    return True


# GGG index-handlers (the `k` on a transform spec) → how to turn the raw stored
# value into the figure the tooltip shows. Non-numeric handlers (passive/skill/
# hash indices we can't resolve) are absent and make a line unrenderable, so we
# omit text rather than print a meaningless number.
def _apply_handler(k: str, x):
    if not isinstance(x, (int, float)):
        return None
    if k in ("canonical_line", "canonical_stat"):
        return x
    if k == "negate":
        return -x
    if k == "double":
        return x * 2
    if k == "negate_and_double":
        return -(x * 2)
    if k == "times_twenty":
        return x * 20
    if k == "multiply_by_four":
        return x * 4
    if k == "subtract_one":
        return x - 1
    if k == "add_one":
        return x + 1
    if k == "plus_two_hundred":
        return x + 200
    if k == "one_hundred_divide_by_value":
        return 100 / x if x else x
    if k == "divide_by_twenty_then_double_0dp":
        return x / 10
    if k == "divide_by_one_hundred_and_negate":
        return -(x / 100)
    if k.startswith("milliseconds_to_seconds"):
        return x / 1000
    if k.startswith("per_minute_to_per_second"):
        return x / 60
    if k.startswith("deciseconds_to_seconds") or k.startswith("divide_by_ten"):
        return x / 10
    if k.startswith("divide_by_one_hundred"):
        return x / 100
    if k.startswith("divide_by_two"):
        return x / 2
    if k == "divide_by_three":
        return x / 3
    if k == "divide_by_four":
        return x / 4
    if k == "divide_by_five":
        return x / 5
    if k.startswith("divide_by_fifteen"):
        return x / 15
    if k == "divide_by_twenty":
        return x / 20
    if k == "divide_by_fifty":
        return x / 50
    return None  # unknown / non-numeric handler -> unrenderable


_DP_RE = re.compile(r"_(\d)dp")


def _display(transforms: dict | None, idx1: int, raw, stat_id: str):
    """The display figure for placeholder idx1 (1-based): apply the variant's
    transform handler if any, else the millisecond-suffix fallback, else the raw
    value. Returns the sentinel _UNRENDERABLE if a handler exists but can't be
    evaluated (so the whole line is dropped)."""
    spec = (transforms or {}).get(str(idx1))
    if spec:
        n = _apply_handler(spec[0], raw)
        if n is None:
            return _UNRENDERABLE
        m = _DP_RE.search(spec[0])
        if m:
            n = round(n, int(m.group(1)))
        elif isinstance(n, float) and not n.is_integer():
            n = round(n, 2)
        return n
    if isinstance(raw, (int, float)) and stat_id.endswith("_ms"):
        return round(raw / 1000, 3)
    return raw


_UNRENDERABLE = object()


def _fmt_number(value, spec: str | None) -> str:
    """Format a value for substitution: honour the sign-forcing spec (`+d`/`+`) and
    trim a trailing `.0` so ints read cleanly."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if spec and spec.startswith("+"):
        return f"{value:+}"
    return str(value)


def _substitute(text: str, displays: dict) -> str:
    """Replace {i}/{i:spec} placeholders with their display values."""
    def repl(m):
        idx = int(m.group(1))
        if idx not in displays:
            return m.group(0)
        return _fmt_number(displays[idx], m.group(2))
    return _PLACEHOLDER.sub(repl, text)


def render(variants: list[dict], value, stat_id: str = "") -> str | None:
    """Render the in-game line for a single-stat value: pick the first variant whose
    limit matches, apply its value transform, and substitute. None if nothing
    matches or the matched variant's handler is unrenderable."""
    for v in variants:
        limits = v.get("limits") or []
        if not _limit_ok(limits[0] if limits else None, value):
            continue
        disp = _display(v.get("transforms"), 1, value, stat_id)
        if disp is _UNRENDERABLE:
            return None
        return _substitute(v["text"], {0: disp})
    return None


def render_multi(stats_ids: list[str], variants: list[dict], valmap: dict) -> str | None:
    """Render a multi-stat line — one that needs several sibling values (e.g. min +
    max damage). None unless every sibling value is present, a variant's per-stat
    limits all match, and every placeholder's transform is renderable."""
    values = [valmap.get(sid) for sid in stats_ids]
    if any(not isinstance(v, (int, float)) for v in values):
        return None
    for var in variants:
        limits = var.get("limits") or []
        if not all(_limit_ok(limits[i] if i < len(limits) else None, values[i])
                   for i in range(len(stats_ids))):
            continue
        displays = {}
        for i, sid in enumerate(stats_ids):
            d = _display(var.get("transforms"), i + 1, values[i], sid)
            if d is _UNRENDERABLE:
                return None
            displays[i] = d
        return _substitute(var["text"], displays)
    return None


def _multi_index(multi: list[dict]) -> dict[str, list[dict]]:
    """Index multi-stat entries by each member stat id, for O(1) lookup at render."""
    idx: dict[str, list[dict]] = {}
    for entry in multi:
        for sid in entry["stats"]:
            idx.setdefault(sid, []).append(entry)
    return idx


class StatDescriptions:
    """The vendored stat-id → in-game-line map, scoped by support vs. active skill.

    Wording differs by scope: a support's lines read "Supported Skills deal …"
    (the `support` scope, from PoB2's gem_stat_descriptions), while an active
    skill's own stats read plain "… increased …" (the `skill` scope). Lookups try
    the scope matching the gem first, then the other as a fallback. Each scope holds
    `single` (one id → variants) and `multi` (entries spanning several ids)."""

    def __init__(self, support: dict, skill: dict, meta: dict | None = None):
        self._support = support.get("single", {})
        self._skill = skill.get("single", {})
        self._support_multi = _multi_index(support.get("multi", []))
        self._skill_multi = _multi_index(skill.get("multi", []))
        self.meta = meta or {}

    def _scopes(self, is_support: bool):
        """(single, multi_index) pairs in priority order for a support vs. active."""
        if is_support:
            return ((self._support, self._support_multi), (self._skill, self._skill_multi))
        return ((self._skill, self._skill_multi), (self._support, self._support_multi))

    def text(self, stat_id: str, value, is_support: bool) -> str | None:
        """The rendered single-stat line for one id+value, or None. (Multi-stat
        lines need sibling values — use render_stats for a gem's full stat list.)"""
        v = 1 if value is True else value
        if not isinstance(v, (int, float)):
            return None
        for single, _ in self._scopes(is_support):
            variants = single.get(stat_id)
            if variants:
                line = render(variants, v, stat_id)
                if line:
                    return line
        return None

    def render_stats(self, stats: list[dict], is_support: bool,
                     quality: bool = False) -> list[str | None]:
        """Render a gem's whole stat list, returning a line (or None) per entry,
        positionally aligned to `stats`. A multi-stat line is attached to its first
        member present and its siblings are marked consumed (None), so the combined
        line shows once. Multi-stat is tried before single, since the combined line
        ("Adds X to Y Damage") supersedes either half alone.

        quality=True renders a `quality_stats` list, whose values are PER 1% of gem
        quality: each value is scaled to 20% quality (the cap) and the line is tagged
        `(at 20% quality)`, so "Chain +0.1 times" becomes "Chain +2 times (at 20%
        quality)" — the decision-relevant payoff of maxing quality."""
        scopes = self._scopes(is_support)
        valmap: dict[str, object] = {}
        for e in stats:
            raw = e.get("value")
            if raw is True:
                v = 1                                   # boolean flag, not a number
            elif quality and isinstance(raw, (int, float)):
                v = round(raw * _MAX_QUALITY, 4)        # per-point -> at 20% quality
            else:
                v = raw
            valmap.setdefault(e["id"], v)
        consumed: set[str] = set()
        out: list[str | None] = []
        for e in stats:
            sid = e["id"]
            if sid in consumed:
                out.append(None)
                continue
            line = None
            for single, multi_idx in scopes:
                for entry in multi_idx.get(sid, []):
                    line = render_multi(entry["stats"], entry["variants"], valmap)
                    if line:
                        consumed.update(entry["stats"])
                        break
                if line:
                    break
            if line is None:
                v = valmap.get(sid)
                if isinstance(v, (int, float)):
                    for single, _ in scopes:
                        variants = single.get(sid)
                        if variants:
                            line = render(variants, v, sid)
                            if line:
                                break
            if line and quality:
                line += _QUALITY_SUFFIX
            out.append(line)
        return out


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
