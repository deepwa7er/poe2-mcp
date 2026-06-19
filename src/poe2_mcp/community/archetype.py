"""Archetype "core vs tech" analysis from a cohort of community builds.

Given a target skill and a cohort of builds (each carrying its active-skill kit,
key passives, and ascendancy), separate the elements most builds SHARE — the
*core* — from the situational variations — the *tech* — and infer which gear
stats to prioritise from what the build actually scales.

The split is by recurrence: an element in at least `core_threshold` of the
cohort is core; one between `tech_floor` and `core_threshold` is tech; rarer than
that is treated as individual noise and dropped.

This module is pure (no network, no protobuf). The caller supplies the cohort
rows (see poeninja.list_builds_with_kits) and a gem-info lookup (name -> dict
with `skill_types` / `is_support`, e.g. GemData.get).
"""

from __future__ import annotations

from collections import Counter
from typing import Callable

GemInfo = Callable[[str], dict | None]

# Persistent buffs whose presence names a damage element the build leans on.
_HERALD_ELEMENT = {
    "herald of ice": "cold",
    "herald of thunder": "lightning",
    "herald of ash": "fire",
    "herald of blood": "physical",
    "herald of plague": "chaos",
}

# Support-gem name fragments that imply a damage element.
_SUPPORT_ELEMENT = {
    "brutality": "physical",
    "fire penetration": "fire",
    "cold penetration": "cold",
    "lightning penetration": "lightning",
}


def _bucket(counter: Counter, n: int, core_threshold: float, tech_floor: float):
    """Split a name->count tally into core / tech lists by fraction of cohort."""
    core, tech = [], []
    for name, c in counter.most_common():
        frac = c / n
        item = {"name": name, "count": c, "of": n, "pct": round(100 * frac)}
        if frac >= core_threshold:
            core.append(item)
        elif frac >= tech_floor:
            tech.append(item)
    return core, tech


def support_breakdown(
    skill_names: list[str],
    build_groups: list[list[dict]],
    *,
    core_threshold: float = 0.6,
    tech_floor: float = 0.2,
) -> dict:
    """For each named skill, find its core vs tech support gems across the cohort.

    `build_groups` is one entry per fetched build: a list of that build's socket
    groups as {"active_skill": str, "supports": [names]}. Support→skill linkage
    isn't in the ladder list, so this needs the actual builds (see the tool).

    A support's fraction is measured against `builds_seen` — the number of builds
    that actually socket that skill — not the whole cohort, so a skill only a few
    builds run is still judged fairly.
    """
    targets = {s.lower(): s for s in skill_names}
    seen = {s: 0 for s in skill_names}
    tallies = {s: Counter() for s in skill_names}

    for groups in build_groups:
        per_skill: dict[str, set] = {}
        for g in groups:
            key = targets.get((g.get("active_skill") or "").lower())
            if key is None:
                continue
            per_skill.setdefault(key, set()).update(g.get("supports") or [])
        for key, sups in per_skill.items():
            seen[key] += 1
            for name in sups:
                tallies[key][name] += 1

    out: dict = {}
    for s in skill_names:
        n = seen[s]
        core, tech = _bucket(tallies[s], n, core_threshold, tech_floor) if n else ([], [])
        out[s] = {"builds_seen": n, "core_supports": core, "tech_supports": tech}
    return out


def tree_breakdown(
    build_passives: list[list[dict]],
    *,
    core_threshold: float = 0.6,
    tech_floor: float = 0.2,
) -> dict:
    """Core vs tech allocated passive tree nodes across the cohort.

    `build_passives` is one entry per fetched build: that build's meaningful
    allocated nodes as {"name": str, "type": "keystone"|"notable", "id": int}.
    The ladder list only carries headline keystones; this needs the actual builds.
    """
    n = len(build_passives)
    if n == 0:
        return {"builds_seen": 0, "core_nodes": [], "tech_nodes": []}

    freq: Counter = Counter()
    node_type: dict[str, str] = {}
    for nodes in build_passives:
        for nm in {nd.get("name") for nd in nodes if nd.get("name")}:
            freq[nm] += 1
        for nd in nodes:
            if nd.get("name"):
                node_type.setdefault(nd["name"], nd.get("type"))

    core, tech = _bucket(freq, n, core_threshold, tech_floor)
    for bucket in (core, tech):
        for item in bucket:
            item["type"] = node_type.get(item["name"])
    return {"builds_seen": n, "core_nodes": core, "tech_nodes": tech}


def analyze_class_tree(
    class_name: str,
    builds: list[dict],
    *,
    core_threshold: float = 0.6,
    tech_floor: float = 0.2,
) -> dict:
    """Core vs tech passive tree nodes for a character class.

    `builds` is the cohort of that class's builds: each {"ascendancy": str,
    "nodes": [ {"name","type","id"} ... ]} (allocated notables/keystones). The
    caller filters the ladder to the class and resolves each build's tree (see the
    analyze_class_tree tool).
    """
    n = len(builds)
    if n == 0:
        return {
            "class": class_name,
            "cohort_size": 0,
            "note": (f"No {class_name!r} builds found in the scanned ladder rows. "
                     "Check the class name, or raise the scan limit."),
        }

    asc: Counter = Counter(b["ascendancy"] for b in builds if b.get("ascendancy"))
    tb = tree_breakdown([b.get("nodes") or [] for b in builds],
                        core_threshold=core_threshold, tech_floor=tech_floor)
    return {
        "class": class_name,
        "cohort_size": n,
        "core_threshold_pct": round(100 * core_threshold),
        "ascendancies": [
            {"name": k, "count": v, "pct": round(100 * v / n)}
            for k, v in asc.most_common()
        ],
        "core_nodes": tb["core_nodes"],
        "tech_nodes": tb["tech_nodes"],
        "note": ("Core = a node allocated by at least the threshold fraction of the "
                 "cohort (the shared tree skeleton); tech = a meaningful minority "
                 "(situational picks). Both list notables and keystones, not small nodes."),
    }


def _gear_priorities(target_tags: set[str], elements: set[str], crit_signal: bool) -> list[dict]:
    """Translate the build's scaling profile into prioritised gear stat targets."""
    is_attack = "Attack" in target_tags
    is_spell = "Spell" in target_tags

    out: list[dict] = [
        {"stat": "Maximum Life", "priority": "core",
         "why": "survivability floor; want it on most slots"},
        {"stat": "Capped Elemental Resistances (75/75/75)", "priority": "core",
         "why": "the hits that kill you are elemental — cap before chasing damage"},
    ]
    if "Spear" in target_tags:
        out.append({"stat": "High physical-DPS spear (weapon)", "priority": "core",
                    "why": "weapon damage multiplies the whole attack kit"})
    if is_attack:
        out.append({"stat": "Increased Attack Speed", "priority": "core",
                    "why": "more hits = more damage, ailments and on-hit effects"})
        out.append({"stat": "Accuracy Rating", "priority": "high",
                    "why": "attacks must land; below ~100% hit chance you lose damage unevenly"})
    if is_spell and not is_attack:
        out.append({"stat": "Increased Cast Speed", "priority": "core",
                    "why": "throughput for a spell-based kit"})
    for el in sorted(elements):
        verb = "to Attacks" if is_attack else "to Spells"
        out.append({"stat": f"Added {el.title()} Damage {verb}", "priority": "high",
                    "why": f"{el} is a core damage source for this kit (heralds/supports)"})
    if "Projectile" in target_tags:
        out.append({"stat": "Projectile Damage / extra projectiles", "priority": "high",
                    "why": "the kit throws projectiles — scales hits and coverage"})
    if "Area" in target_tags:
        out.append({"stat": "Area of Effect / Area Damage", "priority": "medium",
                    "why": "helps clear; trade toward it on mapping gear, away for bossing"})
    if crit_signal:
        out.append({"stat": "Critical Hit Chance + Critical Damage Bonus", "priority": "high",
                    "why": "crit notables/supports are core in this cohort — build into it"})
    else:
        out.append({"stat": "Critical Hit Chance / Bonus", "priority": "tech",
                    "why": "not a core scaler here; only pursue if you pick a crit variant"})
    return out


def analyze(
    skill: str,
    rows: list[dict],
    gem_info: GemInfo,
    *,
    core_threshold: float = 0.6,
    tech_floor: float = 0.2,
    build_groups: list[list[dict]] | None = None,
    build_passives: list[list[dict]] | None = None,
) -> dict:
    """Analyse the cohort of builds using `skill` into core vs tech elements.

    `rows` are cohort builds (each with `skills`, `keypassives`, `class`); only
    those whose kit contains `skill` are kept. Returns a structured report:
    cohort size, ascendancy spread, core/tech skills (split active vs support),
    core/tech key passives, an inferred scaling profile, and gear priorities.

    If `build_groups` is supplied (socket groups from the cohort's actual builds),
    the report also gets `support_breakdown`: the core/tech support gems for the
    target skill and each core skill — linkage that isn't in the ladder list.

    If `build_passives` is supplied (allocated notables/keystones from those
    builds), the report gets `passive_tree`: the core/tech tree nodes — the full
    allocated tree, richer than the ladder's headline keystones.
    """
    want = skill.strip().lower()
    cohort = [r for r in rows if any(want == (s or "").lower() for s in (r.get("skills") or []))]
    n = len(cohort)
    if n == 0:
        return {
            "skill": skill,
            "cohort_size": 0,
            "note": (f"No builds in the current ladder snapshot use {skill!r}. "
                     "Check the skill name, or it may be too rare/off-meta to have a cohort."),
        }

    active_freq: Counter = Counter()
    support_freq: Counter = Counter()
    passive_freq: Counter = Counter()
    ascendancy: Counter = Counter()

    for r in cohort:
        if r.get("class"):
            ascendancy[r["class"]] += 1
        for name in set(r.get("skills") or []):
            if name.lower() == want:
                continue  # the given skill is the premise, not a finding
            info = gem_info(name) or {}
            (support_freq if info.get("is_support") else active_freq)[name] += 1
        for name in set(r.get("keypassives") or []):
            passive_freq[name] += 1

    core_skills, tech_skills = _bucket(active_freq, n, core_threshold, tech_floor)
    core_supports, tech_supports = _bucket(support_freq, n, core_threshold, tech_floor)
    core_passives, tech_passives = _bucket(passive_freq, n, core_threshold, tech_floor)

    # Inferred scaling profile: tags of the TARGET skill (what this build is
    # actually built to scale — unioning the kit pulls in heralds' Spell/Buff
    # tags and muddies the gear advice), plus the damage elements named by the
    # cohort's heralds/supports and a crit signal.
    target_info = gem_info(skill) or {}
    tags: set[str] = set(target_info.get("skill_types") or [])

    elements: set[str] = set()
    all_skill_names = [i["name"] for i in core_skills + tech_skills]
    for name in all_skill_names:
        el = _HERALD_ELEMENT.get(name.lower())
        if el:
            elements.add(el)
    for item in core_supports + tech_supports:
        low = item["name"].lower()
        for frag, el in _SUPPORT_ELEMENT.items():
            if frag in low:
                elements.add(el)
    # Martial attacks scale physical by default unless purely converted.
    if "Attack" in tags and ("Spear" in tags or "Melee" in tags or "Projectile" in tags):
        elements.add("physical")

    crit_signal = any("crit" in i["name"].lower() for i in core_passives) or \
        any("crit" in i["name"].lower() for i in core_supports)

    supports = None
    if build_groups is not None:
        # The target skill is the one they most want supports for, then each core skill.
        skills_for_supports = [skill] + [i["name"] for i in core_skills]
        supports = support_breakdown(
            skills_for_supports, build_groups,
            core_threshold=core_threshold, tech_floor=tech_floor,
        )

    passive_tree = None
    if build_passives is not None:
        passive_tree = tree_breakdown(
            build_passives, core_threshold=core_threshold, tech_floor=tech_floor,
        )

    return {
        "skill": skill,
        "cohort_size": n,
        "core_threshold_pct": round(100 * core_threshold),
        "ascendancies": [
            {"name": k, "count": v, "pct": round(100 * v / n)}
            for k, v in ascendancy.most_common()
        ],
        "core_skills": core_skills,
        "tech_skills": tech_skills,
        "core_supports": core_supports,
        "tech_supports": tech_supports,
        "core_passives": core_passives,
        "tech_passives": tech_passives,
        "scaling_profile": {
            "tags": sorted(tags),
            "damage_elements": sorted(elements),
            "crit_is_core": crit_signal,
        },
        "gear_priorities": _gear_priorities(tags, elements, crit_signal),
        "support_breakdown": supports,
        "passive_tree": passive_tree,
        "note": ("Core = appears in at least the threshold fraction of the cohort; "
                 "tech = a meaningful minority (situational). Supports aren't fully "
                 "captured by the ladder list, so the gear priorities carry the scaling story."),
    }
