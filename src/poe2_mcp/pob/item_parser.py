"""
Parse items from PoB's item text format.

PoB stores items as the verbose text the game client uses. Two layouts appear in
the wild and we handle both:

  * Game-client / PoB1 export — sections separated by lines of dashes ("--------"),
    e.g. a "Quality:" line, then a divider, then "Item Level:", then mods.
  * PoB2 / poe.ninja export — no dash dividers at all; fields are identified purely
    by leading markers ("Item Level:", "Implicits: N", "Rune: ..."), and mod lines
    carry affix tags such as {enchant}, {rune}, {fractured}, {desecrated}, {crafted}.

Treating dash lines as noise and driving the parse off field markers makes the two
layouts converge. Layout of a parsed item:

    Rarity: <rarity>
    <name>
    <base type>            (only Rare/Unique; Magic/Normal fold base into the name)
    <metadata lines...>    (Unique ID:, Item Level:, Quality:, Sockets:, Rune:, ...)
    Implicits: N
    <N implicit mod lines>
    <explicit mod lines>
    Corrupted              (optional flag)

Everything after the metadata block is a mod line; the first `Implicits: N` of
them are implicit (this is why the original dash-only parser silently dropped every
mod on poe.ninja exports — those exports contain no dashes, so the whole item
collapsed into a single header section and the mod-scanning loop never ran).
"""

from __future__ import annotations

import re

_DIVIDER = "--------"
_TAG_RE = re.compile(r"^(?:\{[^}]*\})+")

# Leading markers for non-mod metadata lines (lowercased prefix match). "Bonded:"
# is deliberately absent — it prefixes rune-granted *mods*, not metadata.
_META_PREFIXES = (
    "rarity:", "unique id:", "item level:", "levelreq:", "requirements:",
    "requires ", "quality:", "sockets:", "rune:", "armour:", "evasion:",
    "energy shield:", "ward:", "charm slots:", "stack size:", "limited to:",
    "radius:", "implicits:",
)

# Standalone flag lines (lowercased, exact match).
_FLAG_LINES = {"corrupted", "mirrored", "split", "unidentified"}


def parse_item_text(raw: str, slot: str) -> dict:
    """Return a dict suitable for constructing an Item from raw PoB item text."""
    lines = [
        stripped
        for line in raw.strip().splitlines()
        if (stripped := line.strip()) and stripped != _DIVIDER
    ]
    if not lines:
        return _empty(slot, raw)

    rarity = "Normal"
    name = ""
    base_type = ""
    item_level = 0
    quality = 0
    runes: list[str] = []
    mods: list[str] = []
    corrupted = False
    implicit_count = 0

    i = 0
    if lines[0].lower().startswith("rarity:"):
        rarity = lines[0].split(":", 1)[1].strip().title()
        i = 1

    if i < len(lines):
        name = lines[i]
        i += 1

    # Rare/Unique items name their base type on the next line; Magic/Normal items
    # fold the base into the single name line.
    if rarity in ("Rare", "Unique"):
        if i < len(lines) and not _is_meta(lines[i]) and lines[i].lower() not in _FLAG_LINES:
            base_type = lines[i]
            i += 1
    else:
        base_type = name

    for line in lines[i:]:
        low = line.lower()
        if low.startswith("item level:"):
            item_level = _int_after_colon(line)
        elif low.startswith("quality:"):
            quality = _int_after_colon(line)
        elif low.startswith("rune:"):
            runes.append(line.split(":", 1)[1].strip())
        elif low.startswith("implicits:"):
            implicit_count = _int_after_colon(line)
        elif _is_meta(line):
            continue
        elif low in _FLAG_LINES:
            if low == "corrupted":
                corrupted = True
        else:
            mods.append(_strip_tags(line))

    # Implicits are emitted before explicits, so the first N mods are the implicits.
    implicit_count = min(implicit_count, len(mods))

    return {
        "slot": slot,
        "rarity": rarity,
        "name": name,
        "base_type": base_type,
        "item_level": item_level,
        "quality": quality,
        "runes": runes,
        "mods": mods,
        "implicit_count": implicit_count,
        "corrupted": corrupted,
        "raw_text": raw,
    }


def _is_meta(line: str) -> bool:
    low = line.lower()
    return any(low.startswith(p) for p in _META_PREFIXES)


def _int_after_colon(line: str) -> int:
    try:
        return int(line.split(":", 1)[1].strip())
    except (ValueError, IndexError):
        return 0


def _strip_tags(line: str) -> str:
    """Remove leading affix tags like {enchant}{rune} from a mod line."""
    return _TAG_RE.sub("", line).strip()


def _empty(slot: str, raw: str) -> dict:
    return {
        "slot": slot,
        "rarity": "Normal",
        "name": "",
        "base_type": "",
        "item_level": 0,
        "quality": 0,
        "runes": [],
        "mods": [],
        "implicit_count": 0,
        "corrupted": False,
        "raw_text": raw,
    }
