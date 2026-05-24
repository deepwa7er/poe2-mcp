"""
Interpretation layer on top of a parsed Build.

These functions turn the raw values Path of Building bakes into an export into
actionable findings — passive-point usage and defensive sanity checks. They depend
only on the domain models (no MCP, no tree graph required for diagnostics), so they
are straightforward to unit-test.

PoB stat names vary between versions, so lookups try several candidate names and
report a stat as unavailable rather than assuming zero when it is absent.
"""

from __future__ import annotations

from .pob.models import Build

# Standard maximum elemental resistance in PoE2 unless a build raises it.
DEFAULT_MAX_RESIST = 75.0


def _to_float(value) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", "").rstrip("%").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _stat_lookup(build: Build) -> dict[str, str]:
    return {s.name.lower(): s.value for s in build.stats}


def _find(lookup: dict[str, str], *names: str) -> float | None:
    """Return the first matching stat value (by exact case-insensitive name) as a float."""
    for name in names:
        if name.lower() in lookup:
            v = _to_float(lookup[name.lower()])
            if v is not None:
                return v
    return None


# ---------------------------------------------------------------------------
# Passive point budget
# ---------------------------------------------------------------------------

def summarize_points(build: Build, tree=None) -> dict:
    """
    Summarize how the build spends passive/ascendancy points.

    Splits allocated nodes into normal tree points, ascendancy points, and the
    (free) class start node, using tree data to classify. Without tree data only
    the raw allocated count is known.

    points_from_levels is the number of points granted purely by leveling
    (level - 1). It does NOT include campaign quest points, which are not encoded
    in the export — so it is a lower bound on the points actually available.
    """
    allocated = build.allocated_node_ids
    summary: dict = {
        "level": build.level,
        "class": build.class_name,
        "ascendancy": build.ascendancy,
        "allocated_total": len(allocated),
        "points_from_levels": max(build.level - 1, 0),
        "note": (
            "points_from_levels excludes campaign quest points (not in the export), "
            "so it is a lower bound on points available."
        ),
    }

    if tree is None:
        summary["passive_points_spent"] = None
        summary["ascendancy_points_spent"] = None
        summary["detail"] = "tree data not loaded — cannot classify nodes"
        return summary

    start_ids = set(getattr(tree, "class_start_ids", {}).values())
    normal = ascendancy = start = unresolved = 0
    for nid in allocated:
        node = tree.get(nid)
        if node is None:
            unresolved += 1
        elif nid in start_ids:
            start += 1
        elif node.ascendancy_name:
            ascendancy += 1
        else:
            normal += 1

    summary["passive_points_spent"] = normal
    summary["ascendancy_points_spent"] = ascendancy
    summary["class_start_nodes"] = start
    summary["unresolved_nodes"] = unresolved
    return summary


# ---------------------------------------------------------------------------
# Defensive sanity checks
# ---------------------------------------------------------------------------

_ELEMENTS = (
    ("Fire", "FireResist", "FireResistMax", "FireResistOverCap"),
    ("Cold", "ColdResist", "ColdResistMax", "ColdResistOverCap"),
    ("Lightning", "LightningResist", "LightningResistMax", "LightningResistOverCap"),
)


def analyze_defenses(build: Build) -> list[dict]:
    """
    Return a list of defensive findings for the build.

    Each finding is a dict with: category, severity (ok|warning|critical|info),
    stat, value, and message. Elemental resistances are checked against the
    build's max-resist stat if present, else the standard 75% cap. Findings are
    heuristic; the underlying value is always included so callers can judge.
    """
    lookup = _stat_lookup(build)
    findings: list[dict] = []

    # Elemental resistances
    for label, res_name, max_name, over_name in _ELEMENTS:
        value = _find(lookup, res_name)
        if value is None:
            findings.append({
                "category": "resistance",
                "severity": "info",
                "stat": label,
                "value": None,
                "message": f"{label} resistance not present in export.",
            })
            continue

        cap = _find(lookup, max_name) or DEFAULT_MAX_RESIST
        overcap = _find(lookup, over_name)

        if value < 0:
            severity = "critical"
            message = f"{label} resistance is negative ({value:g}%) — taking heavy {label.lower()} damage."
        elif value < cap:
            severity = "warning"
            message = f"{label} resistance {value:g}% is below the {cap:g}% cap (short {cap - value:g}%)."
        else:
            severity = "ok"
            if overcap and overcap > 0:
                message = f"{label} resistance capped at {cap:g}% with {overcap:g}% overcap."
            else:
                message = f"{label} resistance capped at {cap:g}%."

        findings.append({
            "category": "resistance",
            "severity": severity,
            "stat": label,
            "value": value,
            "message": message,
        })

    # Chaos resistance — uncapped and commonly negative; informational.
    chaos = _find(lookup, "ChaosResist")
    if chaos is None:
        findings.append({
            "category": "resistance", "severity": "info", "stat": "Chaos",
            "value": None, "message": "Chaos resistance not present in export.",
        })
    else:
        sev = "warning" if chaos <= -60 else "info"
        findings.append({
            "category": "resistance", "severity": sev, "stat": "Chaos", "value": chaos,
            "message": f"Chaos resistance is {chaos:g}% (uncapped; negative is common but watch chaos damage).",
        })

    # Health pool
    life = _find(lookup, "Life")
    es = _find(lookup, "EnergyShield")
    ehp = _find(lookup, "TotalEHP")
    pool = (life or 0) + (es or 0)

    if life is not None:
        findings.append({
            "category": "life", "severity": "info", "stat": "Life",
            "value": life, "message": f"Life: {life:g}.",
        })
    if es:
        findings.append({
            "category": "life", "severity": "info", "stat": "EnergyShield",
            "value": es, "message": f"Energy Shield: {es:g}.",
        })
    if ehp is not None:
        findings.append({
            "category": "life", "severity": "info", "stat": "TotalEHP",
            "value": ehp, "message": f"Total effective HP (PoB estimate): {ehp:g}.",
        })

    # Conservative low-pool heuristic for mid/late builds.
    if (life is not None or es) and build.level >= 30 and pool < build.level * 30:
        findings.append({
            "category": "life", "severity": "warning", "stat": "HealthPool",
            "value": pool,
            "message": (
                f"Combined Life+ES ({pool:g}) looks low for level {build.level} "
                f"(heuristic threshold ~{build.level * 30}). Verify survivability."
            ),
        })

    return findings
