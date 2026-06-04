"""
Pack prioritised needs into a single vendor-regex string under a character budget.

The packer is intentionally greedy: take the highest-weight priority first, then
the next, until the next fragment would push the regex over the budget. The
PoE2 vendor search bar accepts ~50 characters, so dropping low-weight needs is
expected — that's why `derive_priorities` already compresses redundant resists
into a single `any_res`.

Each fragment costs `len(fragment) + 1` after the first (the joining `|`). The
in-game search bar already matches case-insensitively and does not interpret
`(?i)`, so the output is a plain alternation — no flags, no anchors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .keywords import FRAGMENTS
from .profile import Priority


@dataclass
class Selection:
    priority: Priority
    fragment: str
    cost: int        # characters this entry contributes (incl. the joining "|")


@dataclass
class Drop:
    priority: Priority
    reason: str      # "no fragment defined" or "budget exhausted"


def build_regex(
    priorities: list[Priority], budget: int = 50,
) -> tuple[str, list[Selection], list[Drop]]:
    """Greedy pack: returns (regex, included, dropped).

    Priorities should already be sorted by weight desc — `derive_priorities`
    does this. Keys that don't appear in FRAGMENTS are dropped with a reason so
    callers can warn about missing fragment definitions.
    """
    selected: list[Selection] = []
    dropped: list[Drop] = []
    used = 0
    for p in priorities:
        frag = FRAGMENTS.get(p.key)
        if frag is None:
            dropped.append(Drop(priority=p, reason="no fragment defined for this key"))
            continue
        cost = len(frag) + (1 if selected else 0)
        if used + cost <= budget:
            selected.append(Selection(priority=p, fragment=frag, cost=cost))
            used += cost
        else:
            dropped.append(Drop(priority=p, reason="budget exhausted"))

    regex = "|".join(s.fragment for s in selected)
    # Sanity check: the regex itself must compile, otherwise we'd hand the user
    # a broken filter. This is a developer-protection step — production keys are
    # static, so a failure here means the FRAGMENTS table needs fixing.
    re.compile(regex or "(?!x)", re.IGNORECASE)
    return regex, selected, dropped
