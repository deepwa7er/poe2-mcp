from poe2_mcp.mechanics.knowledge import (
    explain,
    list_topics,
    mechanics_brief,
    TOPICS,
    PATCH,
)


# -- index -------------------------------------------------------------------

def test_no_argument_returns_index_with_traps():
    idx = explain()
    assert idx["patch"] == PATCH
    assert idx["poe1_traps"]
    slugs = {t["slug"] for t in idx["topics"]}
    # the systems the agent most reliably gets wrong are all present
    assert {"gems", "spirit", "ailments", "defenses"} <= slugs


def test_list_topics_is_index_shaped():
    for t in list_topics():
        assert set(t) == {"slug", "title", "summary"}


# -- topic lookup ------------------------------------------------------------

def test_exact_slug_returns_full_topic():
    t = explain("defenses")
    assert t["slug"] == "defenses"
    assert t["key_facts"] and t["poe1_trap"] and t["see_also"]
    assert t["patch"] == PATCH


def test_lenient_matching_resolves_synonyms():
    # substring of a title/summary/fact, not the slug itself
    assert explain("armour")["slug"] == "defenses"
    assert explain("aura")["slug"] == "spirit-skills"
    assert explain("shock")["slug"] == "ailments"


def test_matching_is_case_insensitive():
    assert explain("DEFENSES")["slug"] == "defenses"


def test_unknown_topic_returns_suggestions_not_crash():
    r = explain("nonsense-xyz")
    assert "error" in r
    assert "topics" in r  # always hand back the index to recover


# -- brief & data integrity --------------------------------------------------

def test_brief_lists_every_topic_slug():
    brief = mechanics_brief()
    assert set(brief["topics"]) == set(TOPICS)
    assert brief["poe1_traps"]


def test_see_also_links_point_at_real_topics():
    for t in TOPICS.values():
        for ref in t["see_also"]:
            assert ref in TOPICS, f"{t['slug']} links to missing topic {ref!r}"
