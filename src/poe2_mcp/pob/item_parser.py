"""
Parse items from PoB's item text format.

PoB stores items in the verbose text format used by the game client:

    Rarity: Rare
    Item Name
    Base Type
    --------
    Sockets: R-G-B
    --------
    Item Level: 86
    --------
    <implicit mod>
    --------
    <explicit mod>
    ...

Sections are delimited by lines of dashes. This parser extracts the fields
we care about for build analysis.
"""

_DIVIDER = "--------"


def parse_item_text(raw: str, slot: str) -> dict:
    """Return a dict suitable for constructing an Item from raw PoB item text."""
    lines = [line.rstrip() for line in raw.strip().splitlines()]
    sections = _split_sections(lines)

    rarity = "Normal"
    name = ""
    base_type = ""
    item_level = 0
    mods: list[str] = []
    corrupted = False

    if not sections:
        return _empty(slot, raw)

    # Section 0: header — Rarity / Name / Base Type
    header = sections[0]
    for line in header:
        if line.lower().startswith("rarity:"):
            rarity = line.split(":", 1)[1].strip()
        elif not name:
            name = line
        elif not base_type and rarity not in ("Normal", "Magic"):
            base_type = line

    # If rarity is Normal or Magic the item has only one name line
    if rarity in ("Normal", "Magic"):
        base_type = name

    # Remaining sections: look for Item Level and mod lines
    for section in sections[1:]:
        for line in section:
            low = line.lower()
            if low.startswith("item level:"):
                try:
                    item_level = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif line == "Corrupted":
                corrupted = True
            elif _is_mod_line(line):
                mods.append(line)

    return {
        "slot": slot,
        "rarity": rarity,
        "name": name,
        "base_type": base_type,
        "item_level": item_level,
        "mods": mods,
        "corrupted": corrupted,
        "raw_text": raw,
    }


def _split_sections(lines: list[str]) -> list[list[str]]:
    sections: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line == _DIVIDER:
            if current:
                sections.append(current)
            current = []
        else:
            current.append(line)
    if current:
        sections.append(current)
    return sections


def _is_mod_line(line: str) -> bool:
    """
    Heuristic: a mod line contains a stat value or a plain descriptor.
    Exclude metadata lines like Sockets, Requirements, Quality, etc.
    """
    skip_prefixes = (
        "sockets:", "requirements:", "quality:", "level:", "str:", "dex:", "int:",
        "item level:", "corrupted", "mirrored", "unidentified", "Elder Item",
        "Shaper Item", "Hunter Item", "Crusader Item", "Redeemer Item", "Warlord Item",
        "{", "}", "note:", "~",
    )
    low = line.lower()
    for prefix in skip_prefixes:
        if low.startswith(prefix.lower()):
            return False
    # Must have actual content
    return bool(line.strip())
