"""
Durable model of how PoE2 core mechanics actually work.

This is "tool memory" for game systems, the sibling of crafting/knowledge.py. The
agent reviewing a build supplies most mechanics reasoning from its own training,
and that training is contaminated with PoE1 assumptions that are WRONG in PoE2
(armour only blocks physical, chaos bypasses ES, evasion only dodges attacks,
support gems are a scarce shared pool, gems gain XP, mana reserves auras...).
Every one of those is false in current PoE2. This module encodes the corrections
as a small set of topics so the agent reasons from how the game actually behaves.

Scope: the systems that (a) matter for reviewing a build and (b) the agent most
reliably gets wrong. It is deliberately conceptual, not a stat encyclopedia —
exact numbers churn per patch, so durable rules and the PoE1 traps lead, and
specific values are flagged as patch-sensitive.

Patch-sensitive: written for 0.5 (Return of the Ancients / Runes of Aldur),
current sub-version 0.5.2. Verify specific numbers against the live game before
quoting them.
"""

from __future__ import annotations

PATCH = "0.5 (Return of the Ancients / Runes of Aldur)"

# The headline corrections: the PoE1 priors that are flatly wrong in PoE2. Kept
# compact so it can ride along on tool outputs and the topic index without bloat.
POE1_TRAPS = [
    "Support gems are NOT a scarce shared pool. Since 0.3 you can socket unlimited "
    "copies of any support; every skill in the kit can be fully and independently "
    "supported. Never advise 'moving' or 'reallocating' a support.",
    "Gems gain NO experience. A gem's level is set when you cut/socket it from an "
    "uncut gem and only changes if you re-cut from a higher one. A support showing "
    "'level 1' in an export is usually a data artifact, not a real downgrade.",
    "Auras / heralds / minions / persistent buffs reserve SPIRIT, not mana. Mana is "
    "left free for casting. Spirit is its own resource with its own sources.",
    "Armour mitigates ALL hit damage types (including elemental and chaos), not just "
    "physical — but it scales against hit SIZE, so it shines vs many small hits and "
    "is weak vs big slams.",
    "Energy Shield is bypassed only by Bleed and Poison. Chaos HITS go through ES "
    "normally now (the PoE1 'chaos ignores ES' rule is gone).",
    "Evasion now avoids enemy SPELLS too (the non-AoE ones), not only attacks. There "
    "is no spell-suppression stat in PoE2.",
    "Crit's damage stat is the 'Critical Damage Bonus', and base values differ from "
    "PoE1's crit multiplier — don't assume PoE1 numbers.",
    "A build is a KIT of several active skills by design (clear skill + boss skill + "
    "utility/combo). Don't collapse it to one skill or one DPS number.",
]


def _topic(slug, title, summary, key_facts, poe1_trap, see_also):
    return {
        "slug": slug,
        "title": title,
        "summary": summary,
        "key_facts": key_facts,
        "poe1_trap": poe1_trap,
        "see_also": see_also,
    }


# Each topic is a durable model of one system: a one-paragraph summary, the
# load-bearing facts, the specific PoE1 prior it corrects, and related topics.
TOPICS = {
    "gems": _topic(
        "gems",
        "Skill & support gems — uncut gems, no XP, unlimited supports",
        "PoE2 gems are items you obtain as UNCUT skill/support gems and 'cut' into a "
        "chosen gem up to the uncut gem's level. Gems do not gain experience: you "
        "raise a gem's level only by cutting it from a higher uncut gem, and you can "
        "re-cut / respec freely. Support gems are not scarce — since 0.3 you can run "
        "unlimited copies of any support, so each active skill in the kit can be fully "
        "and independently supported.",
        [
            "Skill gems and support gems are separate items; you socket supports into "
            "an active skill's links to modify it.",
            "Uncut gems come in tiers (e.g. Lesser / Greater); the uncut tier caps the "
            "level of the gem you cut from it.",
            "No XP-leveling: a gem's level is fixed at cut time. In build exports a "
            "support listed at 'level 1' is typically an artifact of the data, not an "
            "under-leveled gem — don't 'recommend leveling it up'.",
            "Unlimited support copies (post-0.3): the same support can be socketed into "
            "many skills at once. The fix for a weak skill is to ADD/craft the support, "
            "never to move it off another skill.",
            "Quality is applied separately and gives a small scaling bonus; it is not "
            "the main lever.",
            "Some gems are 'spirit gems' — persistent buffs that reserve Spirit rather "
            "than being actively cast (see spirit, spirit-skills).",
        ],
        "PoE1 brain assumes supports are a limited pool to ration and that gems level "
        "by gaining XP in your weapon. Both are false: copies are free and unlimited, "
        "and gem level is set by the uncut gem you cut from.",
        ["spirit", "spirit-skills", "support-scaling"],
    ),
    "spirit": _topic(
        "spirit",
        "Spirit — the reservation resource (not mana)",
        "Spirit is a dedicated resource that PERSISTENT effects reserve: auras, "
        "heralds, persistent minions, and meta/trigger setups. It is separate from "
        "mana, so reserving auras no longer eats your casting pool. Your spirit budget "
        "comes from gear (notably sceptres), the passive tree, and campaign rewards, "
        "and it caps how many persistent effects you can run at once.",
        [
            "Reservation lives on Spirit, NOT mana. Mana is for skill costs; auras/"
            "heralds/minions/persistent buffs draw from Spirit.",
            "Spirit sources: sceptres (large flat Spirit), some other gear, passive "
            "tree, and fixed story/quest rewards. Sceptres are the main lever for a "
            "reservation-heavy build.",
            "Each reserved effect has a Spirit cost; the total cannot exceed your "
            "Spirit. Running more auras/minions means finding more Spirit, not more "
            "mana-reservation efficiency.",
            "Some meta/trigger gems (e.g. Cast on Elemental Ailment-style setups) and "
            "permanent minions are paid for in Spirit too.",
            "Use get_spirit_reservation on a loaded build to see the breakdown.",
        ],
        "PoE1 brain reserves auras against mana/life and optimizes 'reservation "
        "efficiency'. In PoE2 that lever is gone — auras cost Spirit, a separate "
        "budget you grow mostly through sceptres and gear.",
        ["gems", "spirit-skills"],
    ),
    "spirit-skills": _topic(
        "spirit-skills",
        "Spirit-reserved skills — auras, heralds, minions, meta gems",
        "These are the persistent pieces of a kit that sit on the Spirit budget rather "
        "than being cast on demand: auras (party-wide buffs), heralds (on-kill / "
        "on-hit effects), permanent minions, and meta gems that trigger other skills. "
        "When reviewing synergy, treat them as first-class kit members — they often "
        "carry a build's damage multiplier or a key defensive layer.",
        [
            "Auras: persistent buffs to you (and allies/minions). Pick auras whose buff "
            "matches the build's damage type or defensive need.",
            "Heralds: persistent effects that proc on kill/hit, often spreading damage "
            "of a specific element — strong with matching ailment/clear builds.",
            "Minions: permanent summons reserve Spirit; their damage scales off minion "
            "stats and supports, not the caster's weapon.",
            "Meta / trigger gems: reserve Spirit to automatically cast a linked skill "
            "on a condition (e.g. on ailment, on crit) — powerful but Spirit-hungry.",
            "Because all of these share the Spirit pool, the build's ceiling on "
            "persistent power is its Spirit, not its mana (see spirit).",
        ],
        "PoE1 brain treats auras/heralds as 'free' once reserved and minions as a mana "
        "concern. In PoE2 every persistent effect competes for the same Spirit budget, "
        "so the trade-off is which buffs are worth their Spirit.",
        ["spirit", "gems"],
    ),
    "ailments": _topic(
        "ailments",
        "Ailments — damaging (bleed/poison/ignite) and non-damaging (chill/freeze/shock/electrocute)",
        "Ailments are status effects a hit can inflict. Damaging ailments deal damage "
        "over time scaled off the hit that applied them; non-damaging ailments debuff "
        "the target. Each is tied to a damage type, which is what lets the build's "
        "scaling (and support-gem) choices line up with the ailment it wants to apply.",
        [
            "Bleeding: physical DoT, ~5s. Bypasses Energy Shield. Magnitude scales off "
            "the physical damage of the applying hit (~70%/s baseline).",
            "Poison: chaos DoT, ~2s, STACKS. Bypasses Energy Shield. Scales off the "
            "pre-mitigation physical + chaos of the hit (~20%/s per stack baseline).",
            "Ignite: fire DoT, ~4s. Scales off the fire damage of the applying hit "
            "(~20%/s baseline).",
            "Chill: slows the target (magnitude scales with hit size vs the target's "
            "ailment threshold), ~2s.",
            "Freeze: target cannot act; applied via freeze buildup, ~4s when it "
            "triggers. Cold-damage driven.",
            "Shock: increases damage the target TAKES from subsequent hits (a 'more "
            "damage taken' multiplier whose magnitude scales with the shock hit). "
            "Lightning-driven.",
            "Electrocute: a lightning-driven buildup ailment that interrupts/stuns the "
            "target once it fills.",
            "Damage-type mapping (for matching tree/supports): ignite/burn->fire, "
            "freeze/chill->cold, shock/electrocute->lightning, bleed->physical, "
            "poison->chaos.",
            "Numbers are patch-sensitive baselines — verify before quoting exact "
            "magnitudes/durations.",
        ],
        "PoE1 brain assumes only the single biggest ignite applies, that shock is a "
        "fixed bonus, and PoE1 durations/magnitudes. PoE2 tunes these differently "
        "(e.g. shock magnitude scales, poison stacks) — match the build's damage type "
        "to its intended ailment and don't quote PoE1 numbers.",
        ["damage-conversion", "crit", "defenses"],
    ),
    "defenses": _topic(
        "defenses",
        "Defensive layers — armour, evasion, energy shield, block, resistances",
        "PoE2 defense is layered and each layer behaves differently from PoE1. Armour "
        "mitigates a share of every hit but scales against hit SIZE. Evasion avoids "
        "attacks AND non-AoE spells via an entropy system. Energy Shield is a buffer "
        "in front of life, bypassed only by bleed/poison. Block can fully negate a "
        "hit. Resistances cap incoming elemental/chaos damage. A real build stacks "
        "more than one of these — a single layer is fragile.",
        [
            "Armour: Damage Reduction = Armour / (Armour + 12 * damage taken). It "
            "applies to ALL hit damage types (not just physical), but its value falls "
            "as the hit grows — great vs many small hits, weak vs big slams.",
            "Evasion: chance to avoid attack hits and non-AoE spell hits, governed by "
            "an entropy counter (so it's consistent, not pure RNG). There is NO "
            "spell-suppression stat in PoE2; evasion is your spell-dodging layer.",
            "Energy Shield: a buffer that takes hits before life and recharges after a "
            "delay. Bypassed ONLY by Bleed and Poison — chaos HITS deplete ES normally "
            "(unlike PoE1).",
            "Block: a chance to fully prevent an incoming strike/projectile hit and the "
            "ailments it would have applied. Pairs well with armour/ES.",
            "Resistances: fire/cold/lightning/chaos, default cap 75% (raisable). "
            "Uncapped or negative resists are a critical defensive hole — check first.",
            "Layering matters: armour-only dies to big hits, evasion-only dies to the "
            "hit that lands, ES-only dies to bleed/poison. Look for at least two "
            "complementary layers plus capped resists.",
        ],
        "PoE1 brain assumes armour is physical-only, chaos ignores ES, evasion only "
        "dodges attacks, and spell suppression exists. All four are wrong in PoE2: "
        "armour is universal-but-size-scaled, chaos hits ES, evasion covers non-AoE "
        "spells, and there is no suppression.",
        ["ailments", "resistances", "attributes"],
    ),
    "resistances": _topic(
        "resistances",
        "Resistances, penetration & exposure",
        "Resistances reduce incoming damage of their element (fire/cold/lightning) or "
        "chaos; the player cap is 75% by default and is the single most important "
        "defensive number to get to cap. On the offense side, penetration and exposure "
        "lower an ENEMY's resistances so your hits land harder.",
        [
            "Player elemental/chaos resistances cap at 75% by default; some sources "
            "raise the max. Get all of them to cap before chasing more life/ES.",
            "Negative resistances (common while levelling or after a tough map mod) "
            "mean you take INCREASED damage of that type — a top-priority fix.",
            "Penetration: your hits ignore a flat % of the enemy's resistance to that "
            "element (only useful if the build deals that element).",
            "Exposure: applies a debuff that LOWERS the enemy's resistance to an "
            "element; stacks with penetration but they are different mechanics.",
            "Match offensive res-shred to your damage type — lightning penetration does "
            "nothing for a cold build.",
        ],
        "PoE1 brain remembers chaos resistance as a near-afterthought that didn't "
        "matter because chaos bypassed ES. In PoE2 chaos hits ES and life normally, so "
        "chaos resistance is a real defensive stat.",
        ["defenses", "damage-conversion"],
    ),
    "damage-conversion": _topic(
        "damage-conversion",
        "Damage conversion & 'gain as' added damage",
        "Skills deal a base damage of one or more types; conversion turns a portion of "
        "one type into another, and 'gain X% as' adds extra damage of another type "
        "without removing the source. The order matters because INCREASES to both the "
        "original and the final type apply to converted damage — this is how a build "
        "stacks two damage axes onto one hit.",
        [
            "Conversion moves damage from one type to another (e.g. phys->cold); 'gain "
            "as' adds a copy as another type without reducing the original.",
            "Total conversion of a given source can't exceed 100%; leftover stays its "
            "original type.",
            "Converted damage is boosted by increases/more to BOTH the original type "
            "and the resulting type — this double-dipping is the point of conversion "
            "builds.",
            "Ailments scale off the post-conversion damage of the hit, so conversion "
            "decides which ailment you can apply (see ailments).",
            "Penetration/resistance that applies is the FINAL damage type's, not the "
            "original's.",
        ],
        "Conversion mechanics are broadly similar to PoE1, so the trap here is subtler: "
        "don't assume specific conversion sources/values from PoE1 still exist — verify "
        "the skill/support/tree actually provides the conversion before scaling for it.",
        ["ailments", "resistances", "crit"],
    ),
    "crit": _topic(
        "crit",
        "Critical hits — chance and Critical Damage Bonus",
        "Critical hits multiply a hit's damage. A build scales crit via Critical Hit "
        "Chance (how often) and Critical Damage Bonus (how much extra), both sourced "
        "from weapon, gems, tree and gear. PoE2 base values and the stat naming differ "
        "from PoE1, so don't carry over PoE1 multiplier numbers.",
        [
            "Two levers: Critical Hit Chance (frequency) and Critical Damage Bonus "
            "(magnitude). Both need investment for crit to pay off — chance without "
            "bonus, or bonus without chance, is weak.",
            "Base crit chance comes largely from the weapon; spells get it from the "
            "gem. Power charges boost crit chance.",
            "The damage stat is 'Critical Damage Bonus' (PoE1 called it crit "
            "multiplier); base magnitude differs from PoE1 — verify, don't assume.",
            "Crit is one scaling axis among several (raw added damage, ailments, "
            "conversion); a non-crit build that invests in crit-on-gear is leaking "
            "stats (note this LAST, as a gear criterion).",
        ],
        "PoE1 brain assumes 150% base crit multiplier and PoE1 crit math. PoE2 renames "
        "and re-tunes it as Critical Damage Bonus — check the build's actual values "
        "rather than reciting PoE1 numbers.",
        ["charges", "damage-conversion", "ailments"],
    ),
    "charges": _topic(
        "charges",
        "Charges — Power, Frenzy, Endurance",
        "Charges are stacking, temporary buffs gained on certain conditions (kills, "
        "crits, skill use) up to a maximum. The three classic charges each push a "
        "different axis, and many builds generate them automatically as a baked-in "
        "multiplier — get_stats may report buffed or unbuffed depending on config.",
        [
            "Power charges: increase critical hit chance (and some spell scaling) — for "
            "crit/spell builds.",
            "Frenzy charges: increase attack and cast speed and add a small more-damage "
            "multiplier — for fast attack/cast builds.",
            "Endurance charges: physical damage reduction and elemental resistance — a "
            "defensive layer.",
            "Each has a max count (3 by default) that gear/tree can raise; generation "
            "and max are separate problems.",
            "Whether DPS figures include charges depends on the saved config — read "
            "get_config and use recompute_stats to compare charged vs uncharged.",
        ],
        "Charge mechanics resemble PoE1, but generation sources differ — confirm the "
        "build can actually generate and sustain a charge before counting its bonus.",
        ["crit", "defenses"],
    ),
    "attributes": _topic(
        "attributes",
        "Attributes — Strength, Dexterity, Intelligence and gem requirements",
        "The three attributes both gate gem use and grant passive bonuses. Each skill/"
        "support gem has attribute requirements you must meet to socket it, and your "
        "attribute totals also give defensive/offensive bonuses. A build's class and "
        "tree starting area bias which attributes come easily.",
        [
            "Gems have attribute requirements — a high-Int caster may be unable to "
            "socket a Str/Dex gem without sourcing that attribute from tree/gear.",
            "Attributes grant bonuses (broadly: Strength -> life, Dexterity -> "
            "accuracy/evasion-leaning, Intelligence -> mana), plus they unlock content "
            "and gear requirements.",
            "Hybrid kits (e.g. a caster wanting an attack utility skill) often need a "
            "few attribute nodes or a gear roll to meet a gem's requirement.",
            "Don't recommend a gem the build can't meet the attribute requirement for "
            "without also pointing at where the attribute comes from.",
            "Exact per-point bonuses are patch-sensitive — verify before quoting.",
        ],
        "PoE1 brain remembers the exact per-point attribute bonuses; PoE2 tunes these "
        "differently. Treat attributes mainly as gem-requirement gates plus broad "
        "bonuses, and check requirements before recommending off-class gems.",
        ["gems", "defenses"],
    ),
    "ascendancy": _topic(
        "ascendancy",
        "Ascendancy — class specialisations and their points",
        "Each class has Ascendancy classes that grant powerful specialised nodes on a "
        "separate small tree, earned by completing trials. Ascendancy nodes usually "
        "define a build's identity (its key multiplier or mechanic), so synergy "
        "analysis should weigh them heavily alongside the main tree.",
        [
            "Ascendancy points come from completing trials, not from levels; the small "
            "ascendancy tree is separate from the main passive tree.",
            "Ascendancy notables are build-defining — they often grant a unique "
            "mechanic or a large multiplier the rest of the build is built around.",
            "When identifying the build (review step 0), the ascendancy is one of the "
            "strongest signals of intended archetype.",
            "Treat dead ascendancy investment (nodes that scale an axis the kit doesn't "
            "use) as a high-value finding, same as dead main-tree investment.",
            "Specific ascendancy rosters and node effects are patch-sensitive — confirm "
            "against the live game / the loaded build's actual nodes.",
        ],
        "PoE1 brain assumes 8 ascendancy points from 4 fixed lab trials and specific "
        "PoE1 ascendancies. PoE2's ascendancy classes, trials and point counts differ "
        "— read the build's actual ascendancy nodes rather than assuming.",
        ["gems", "spirit-skills"],
    ),
    "support-scaling": _topic(
        "support-scaling",
        "How supports scale a skill — applicability before power",
        "A support only helps if it APPLIES to the skill: its tags (spell/attack/"
        "melee/projectile/area), damage type, and any condition must match what the "
        "skill does. Because copies are unlimited, the question is never 'which skill "
        "deserves this support' but 'which applicable supports most raise THIS skill'.",
        [
            "A support must match the skill's tags and damage dimension to do anything "
            "(a melee-only support on a spell is dead).",
            "recommend_supports buckets compatible supports as penetration / "
            "unconditional-more / conditional / utility — prefer unconditional 'more' "
            "multipliers, then conditionals the build can reliably meet.",
            "Conditional supports (need an ailment, a charge, low life, etc.) only pay "
            "off if the build actually satisfies the condition — check before counting "
            "them.",
            "Every skill in the kit can run its own full set of supports (unlimited "
            "copies), so support a boss skill and a clear skill independently.",
            "Quality and gem level on the support add a little; the bucket (more vs "
            "conditional vs utility) matters more than fine-tuning quality.",
        ],
        "PoE1 brain treats supports as a scarce pool to allocate across skills. In "
        "PoE2 they're unlimited, so the only real question is applicability and "
        "multiplier size for each individual skill.",
        ["gems", "ailments", "crit"],
    ),
}


def list_topics() -> list[dict]:
    """The topic index: slug + title + summary for every mechanic, plus the traps."""
    return [
        {"slug": t["slug"], "title": t["title"], "summary": t["summary"]}
        for t in TOPICS.values()
    ]


def explain(topic: str | None = None) -> dict:
    """Return one topic's durable model, or the index when topic is missing/unknown.

    Matching is lenient: case-insensitive, and a topic resolves if the query is a
    substring of (or contained in) the slug or title, so 'armour' finds 'defenses',
    'aura' finds 'spirit-skills', etc.
    """
    if not topic:
        return {
            "patch": PATCH,
            "poe1_traps": POE1_TRAPS,
            "topics": list_topics(),
            "usage": "call explain_mechanic('<slug>') for any topic above; matching "
                     "is lenient (e.g. 'armour' -> defenses, 'aura' -> spirit-skills).",
        }

    q = topic.strip().lower()
    # Exact slug first, then lenient substring match against slug + title + summary.
    if q in TOPICS:
        return {"patch": PATCH, **TOPICS[q]}
    for t in TOPICS.values():
        if q in t["slug"] or q in t["title"].lower():
            return {"patch": PATCH, **t}
    matches = [
        t for t in TOPICS.values()
        if q in t["summary"].lower() or any(q in f.lower() for f in t["key_facts"])
    ]
    if len(matches) == 1:
        return {"patch": PATCH, **matches[0]}

    return {
        "error": f"No mechanic topic matches {topic!r}.",
        "did_you_mean": [t["slug"] for t in matches][:5],
        "topics": list_topics(),
        "patch": PATCH,
    }


def mechanics_brief() -> dict:
    """Compact ride-along for tool outputs: the PoE1 traps + the topic slugs.

    Small enough to attach to a review-oriented response without bloating it; the
    full model for any topic is one explain_mechanic call away.
    """
    return {
        "poe1_traps": POE1_TRAPS,
        "topics": [t["slug"] for t in TOPICS.values()],
        "patch": PATCH,
        "full_model": "call explain_mechanic('<slug>') for any topic, or with no "
                      "argument for the index.",
    }
