"""
Load the vendored crafting database (affix pool + base types) and answer the
questions a craft advisor needs.

The database is generated from the RePoE-fork PoE2 export by
scripts/build_craft_data.py and shipped as data/poe2_crafting.json:

    { "meta": {...},
      "mods":  [ {id, type, group, gen, name, lvl, text, sw}, ... ],
      "bases": { "<lower name>": {name, cls, tags, lvl}, ... } }

`gen` is "prefix" or "suffix"; `text` is the cleaned game-tooltip wording with a
numeric range (e.g. "+(16-20)% to Cold Resistance"); `sw` is the ordered
spawn-weight list [[tag, weight], ...].

Two capabilities sit on top of this:
  * mods_for_base — which affixes can roll on a given base (with tiers/weights),
    optionally filtered by a stat keyword or prefix/suffix.
  * classify_mod_line — map a rolled mod line on an item back to prefix/suffix, so
    the advisor can count how many prefix/suffix slots an item has used.

The server works without the file — the crafting tools report it is missing.
Set CRAFT_DATA_PATH to override the default location.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .._resources import resource_path
from .runes import RuneData, load_default_rune_data

# Rollable explicit mods are capped at 3 prefixes + 3 suffixes on a Rare; Magic
# allows one of each. Used by the advisor for slot accounting.
MAX_AFFIXES = {"rare": 3, "magic": 1, "normal": 0}

# A parenthesised range "(6-10)" / "(-25)" or a bare number "38" / "1.5".
_NUM = re.compile(r"\(-?[0-9.]+(?:-[0-9.]+)?\)|-?\d+(?:\.\d+)?")

# A signed decimal, optionally followed by "-<signed decimal>" (a range). Used to
# split a single _NUM token into its (lo, hi) bounds.
_RANGE = re.compile(r"^(-?\d+(?:\.\d+)?)(?:-(-?\d+(?:\.\d+)?))?$")


def _parse_range(token: str) -> tuple[float, float] | None:
    """Parse one _NUM token into (lo, hi). A bare number becomes (n, n); a range
    "(150-174)" becomes (150.0, 174.0). Returns None if it doesn't parse."""
    m = _RANGE.match(token.strip().strip("()"))
    if not m:
        return None
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) is not None else lo
    return (lo, hi)


def _template_ranges(text: str) -> list[tuple[float, float]]:
    """The numeric bounds of every value slot in a mod template, in order."""
    out = []
    for mt in _NUM.finditer(text):
        rng = _parse_range(mt.group(0))
        if rng is not None:
            out.append(rng)
    return out


def _rolled_values(line: str) -> list[float]:
    """The concrete numbers in a rolled mod line, in order. A rolled line carries
    plain numbers (no parenthesised ranges), so every token is a single value."""
    out = []
    for mt in _NUM.finditer(line):
        try:
            out.append(float(mt.group(0).strip("()")))
        except ValueError:
            continue
    return out


def _pattern_for(text: str) -> str:
    """Build a regex string that matches a rolled instance of a mod's template.

    Numbers/ranges in the template become a signed-number wildcard; literal text
    is escaped and runs of whitespace are made flexible so tooltip spacing differs
    are tolerated.
    """
    parts: list[str] = []
    last = 0
    for mt in _NUM.finditer(text):
        parts.append(re.escape(text[last:mt.start()]))
        parts.append(r"[+-]?\d+(?:\.\d+)?")
        last = mt.end()
    parts.append(re.escape(text[last:]))
    pat = "".join(parts)
    # Collapse any run of whitespace — escaped ("\ ") or literal — into \s+, so
    # tooltip spacing differences don't break the match. (re.escape escapes spaces
    # on some Python versions, hence the optional leading backslash.)
    pat = re.sub(r"(?:\\?\s)+", r"\\s+", pat)
    return "^" + pat + "$"


class CraftData:
    def __init__(self, mods: list[dict], bases: dict[str, dict], meta: dict | None = None,
                 runes: "RuneData | None" = None):
        self.mods = mods
        self.bases = bases
        self.meta = meta or {}
        # Optional rune/soul-core grants (real per-slot values). When present,
        # rune_options returns concrete granted lines; absent, it returns [].
        self._runes = runes
        self._build_classifier()
        # type -> its tiers (every mod sharing that mod type), best tier last.
        # A "type" is one stat ladder (e.g. IncreasedLife); the trailing numeral on
        # the id is the tier. Higher lvl = higher tier = better roll values.
        self._by_type: dict[str, list[dict]] = {}
        for m in self.mods:
            self._by_type.setdefault(m["type"], []).append(m)
        for tiers in self._by_type.values():
            tiers.sort(key=lambda m: m["lvl"])

    def _build_classifier(self) -> None:
        # Dedupe by template pattern; remember which generation_type(s) and mod
        # type(s) render to it. A pattern that maps to a single gen classifies
        # confidently; one that maps to several is ambiguous and left unclassified.
        agg: dict[str, dict] = {}
        for m in self.mods:
            text = m.get("text") or ""
            if not text:
                continue
            ps = _pattern_for(text)
            entry = agg.setdefault(ps, {"gens": set(), "types": set()})
            entry["gens"].add(m["gen"])
            entry["types"].add(m["type"])
        self._classifiers: list[tuple[re.Pattern, str | None, str | None]] = []
        for ps, entry in agg.items():
            gen = next(iter(entry["gens"])) if len(entry["gens"]) == 1 else None
            typ = next(iter(entry["types"])) if len(entry["types"]) == 1 else None
            self._classifiers.append((re.compile(ps, re.IGNORECASE), gen, typ))

    # -- base resolution ----------------------------------------------------

    def resolve_base(self, base_type: str) -> dict | None:
        """Resolve an item's base type to its base record (name, cls, tags, lvl).

        Tries an exact (case-insensitive) name match first; failing that — e.g. a
        Magic item whose base is wrapped in affixes — falls back to the longest
        known base name that appears as a substring of the given text.
        """
        if not base_type:
            return None
        key = base_type.strip().lower()
        if key in self.bases:
            return self.bases[key]
        best: dict | None = None
        for name, rec in self.bases.items():
            if name in key and (best is None or len(name) > len(best["name"])):
                best = rec
        return best

    # -- spawn weights ------------------------------------------------------

    @staticmethod
    def weight_for_base(mod: dict, base_tags: set[str]) -> int:
        """Weight of `mod` on a base with `base_tags`, using PoE's first-match rule.

        Spawn weights are evaluated in order; the first entry whose tag the base
        has (or the catch-all "default") decides the weight. A 0 on a specific tag
        therefore excludes the base even if a broader later tag would match.
        """
        for tag, weight in mod["sw"]:
            if tag in base_tags or tag == "default":
                return weight
        return 0

    def mods_for_base(
        self, base_type: str, keyword: str | None = None, kind: str | None = None
    ) -> dict:
        """Affixes that can roll on `base_type`, grouped by mod type into tiers.

        keyword filters by a case-insensitive substring of the mod text/type/group;
        kind filters to "prefix" or "suffix". Returns {base, item_class, groups:[...]}
        where each group has type/gen/weight and its tiers (name, text, lvl), or an
        {error} if the base is unknown.
        """
        rec = self.resolve_base(base_type)
        if rec is None:
            return {"error": f"Unknown base type {base_type!r} — not in the crafting data."}
        tags = set(rec["tags"])
        kw = keyword.lower() if keyword else None

        grouped: dict[str, dict] = {}
        for m in self.mods:
            if kind and m["gen"] != kind:
                continue
            weight = self.weight_for_base(m, tags)
            if weight <= 0:
                continue
            if kw and not (kw in m["text"].lower() or kw in m["type"].lower()
                           or kw in m["group"].lower()):
                continue
            g = grouped.setdefault(m["type"], {
                "type": m["type"], "group": m["group"], "gen": m["gen"],
                "weight": weight, "tiers": [],
            })
            g["tiers"].append({"name": m["name"], "text": m["text"], "lvl": m["lvl"]})

        for g in grouped.values():
            g["tiers"].sort(key=lambda t: t["lvl"])
        groups = sorted(grouped.values(), key=lambda g: (g["gen"], -g["weight"], g["type"]))
        return {"base": rec["name"], "item_class": rec["cls"], "groups": groups}

    # -- classification -----------------------------------------------------

    def classify_mod_line(self, line: str) -> tuple[str | None, str | None]:
        """Map a rolled mod line to (generation_type, mod_type), best-effort.

        Returns (None, None) when no template matches or the match is ambiguous
        (the same wording rolls as both a prefix and a suffix on different mods).
        """
        text = line.strip()
        for pat, gen, typ in self._classifiers:
            if pat.match(text):
                return gen, typ
        return None, None

    # -- tier matching ------------------------------------------------------

    def match_rolled_line(
        self, line: str, base_tags: set[str] | None = None, ilvl: int | None = None
    ) -> dict | None:
        """Place a rolled mod line on its tier ladder.

        Classifies the line to a mod type, then finds which tier it rolled (the tier
        whose value range contains the rolled number) and how good that roll is.
        Returns None when the line can't be classified (exotic/unique/essence-only
        wording, or ambiguous) — the caller should report it as unmatched, not guess.

        With `base_tags`, tiers that can't roll on that base (spawn weight 0) are
        excluded, so the tier count reflects this item's real ladder. With `ilvl`,
        the result flags whether a better tier is already reachable at this item
        level or only at a higher one.

        Result keys: type, gen, tier (1 = best), tier_count, tier_lvl (ilvl that
        unlocks the rolled tier), roll_pct (0-100, position of the roll inside its
        tier's range; None if the tier has no variable value), values, value_range,
        best_tier_at_ilvl, next_better_tier_lvl (ilvl unlocking the next-better tier,
        or None if already top), at_best_for_ilvl (no better tier reachable now).
        """
        gen, typ = self.classify_mod_line(line)
        if typ is None:
            return None
        tiers = self._by_type.get(typ) or []
        if base_tags is not None:
            tiers = [t for t in tiers if self.weight_for_base(t, base_tags) > 0]
        if not tiers:
            return None

        values = _rolled_values(line)
        primary = values[0] if values else None

        # Choose the tier whose primary range contains the rolled value; if the roll
        # sits above every tier (quality/aug pushed it past the printed max) take the
        # top tier, if below every tier take the bottom. Tiers are lvl-ascending.
        chosen_idx = 0
        if primary is not None:
            chosen_idx = None
            for i, t in enumerate(tiers):
                rngs = _template_ranges(t["text"])
                if not rngs:
                    continue
                lo, hi = rngs[0]
                if lo <= primary <= hi:
                    chosen_idx = i
                    break
            if chosen_idx is None:
                # Above the top tier's max, or below the bottom tier's min.
                top = _template_ranges(tiers[-1]["text"])
                chosen_idx = len(tiers) - 1 if (top and primary >= top[0][1]) else 0
        chosen = tiers[chosen_idx]

        # roll_pct: average position of each variable value within its tier range.
        pcts = []
        for (lo, hi), v in zip(_template_ranges(chosen["text"]), values):
            if hi != lo:
                # Clamp: a roll can't legitimately sit outside its tier's printed
                # range; out-of-range means quality adjusted the shown value or a
                # local/global wording collision, not a real >100%/<0% roll.
                pcts.append(min(1.0, max(0.0, (v - lo) / (hi - lo))))
        roll_pct = round(100 * sum(pcts) / len(pcts), 1) if pcts else None

        n = len(tiers)
        tier_rank = n - chosen_idx  # 1 = best
        best_at_ilvl_idx = None
        if ilvl is not None:
            reachable = [i for i, t in enumerate(tiers) if t["lvl"] <= ilvl]
            if reachable:
                best_at_ilvl_idx = max(reachable)
        # The next-better tier above the rolled one (None if already top).
        next_better = tiers[chosen_idx + 1] if chosen_idx + 1 < n else None

        rng = _template_ranges(chosen["text"])
        return {
            "type": typ,
            "gen": gen,
            "tier": tier_rank,
            "tier_count": n,
            "tier_lvl": chosen["lvl"],
            "roll_pct": roll_pct,
            "values": values,
            "value_range": rng[0] if rng else None,
            "best_tier_at_ilvl": (n - best_at_ilvl_idx) if best_at_ilvl_idx is not None else None,
            "at_best_for_ilvl": best_at_ilvl_idx is not None and best_at_ilvl_idx <= chosen_idx,
            "next_better_tier_lvl": next_better["lvl"] if next_better else None,
        }

    # -- runes --------------------------------------------------------------

    def rune_options(self, keyword: str, item_class: str) -> list[dict]:
        """Runes/soul cores that grant `keyword` for `item_class`, with their real
        per-slot values (e.g. "+14% to Cold Resistance"). Empty if no rune data is
        loaded or none match."""
        if self._runes is None:
            return []
        return self._runes.grants(keyword, item_class)


def load_craft_data(path: str | Path, runes: "RuneData | None" = None) -> CraftData:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return CraftData(data.get("mods", []), data.get("bases", {}), data.get("meta", {}), runes)


def load_default_craft_data() -> CraftData | None:
    """Load the crafting database from the default path, or None if absent. Also
    loads the rune data if present, so craft advice can quote real rune values."""
    env_path = os.environ.get("CRAFT_DATA_PATH")
    path = Path(env_path) if env_path else resource_path("data", "poe2_crafting.json")
    if not path.exists():
        return None
    return load_craft_data(path, load_default_rune_data())
