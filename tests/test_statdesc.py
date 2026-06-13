from poe2_mcp.skills.statdesc import (
    parse_stat_descriptions,
    render,
    StatDescriptions,
    _LuaTableParser,
)


# A compact stat-description table covering the cases that matter: a penetration
# line, an increased/reduced pair selected by limit sign, a sign-forced level line,
# a millisecond duration, a multi-stat line (skipped in Phase 1), and the rare "!"
# negation bound.
SAMPLE = r"""
return {
    [1]={
        [1]={ [1]={ limit={ {1,"#"} }, text="Penetrate {0}% Fire Resistance" } },
        stats={ [1]="reduce_fire_res" }
    },
    [2]={
        [1]={
            [1]={ limit={ {1,"#"} }, text="{0}% increased Attack Speed" },
            [2]={ limit={ {"#",-1} }, text="{0}% reduced Attack Speed" }
        },
        stats={ [1]="attack_speed_+%" }
    },
    [3]={
        [1]={ [1]={ limit={ {1,"#"} }, text="{0:+d} to Level of Supported Skills" } },
        stats={ [1]="gem_level_+" }
    },
    [4]={
        [1]={ [1]={ limit={ {"#","#"} }, text="Trigger every {0} seconds" } },
        stats={ [1]="trigger_interval_ms" }
    },
    [5]={
        [1]={ [1]={ limit={ {"#","#"},{"#","#"} }, text="Adds {0} to {1} Damage" } },
        stats={ [1]="min_dmg", [2]="max_dmg" }
    },
    [6]={
        [1]={ [1]={ limit={ {"!","#"} }, text="never matches" } },
        stats={ [1]="weird" }
    }
}
"""


def _parsed():
    return parse_stat_descriptions(SAMPLE)


# -- parsing -----------------------------------------------------------------

def test_positional_and_keyed_entries_parse():
    root = _LuaTableParser(SAMPLE).parse_return()
    # top-level positional entries are 1-based integer keys
    assert set(root) == {1, 2, 3, 4, 5, 6}


def test_single_stat_lines_kept_multi_stat_dropped():
    d = _parsed()
    assert "reduce_fire_res" in d
    assert "min_dmg" not in d and "max_dmg" not in d  # multi-stat: Phase 2


# -- rendering ---------------------------------------------------------------

def test_renders_value_into_template():
    assert render(_parsed()["reduce_fire_res"], 30) == "Penetrate 30% Fire Resistance"


def test_limit_selects_increased_vs_reduced():
    v = _parsed()["attack_speed_+%"]
    assert render(v, 10) == "10% increased Attack Speed"
    assert render(v, -10) == "-10% reduced Attack Speed"


def test_sign_forcing_format_spec():
    assert render(_parsed()["gem_level_+"], 2) == "+2 to Level of Supported Skills"


def test_no_matching_variant_returns_none():
    # value 0 satisfies neither >=1 nor <=-1
    assert render(_parsed()["attack_speed_+%"], 0) is None


def test_non_numeric_bound_is_skipped():
    # the "!" sentinel can't be evaluated, so the only variant never matches
    assert render(_parsed()["weird"], 5) is None


# -- StatDescriptions: scope + transforms ------------------------------------

def test_ms_transform_renders_seconds():
    sd = StatDescriptions(support={}, skill=_parsed())
    assert sd.text("trigger_interval_ms", 3000, is_support=False) == "Trigger every 3 seconds"


def test_scope_preference_support_vs_skill():
    support = {"x": [{"limits": [[None, None]], "text": "Supported Skills: X"}]}
    skill = {"x": [{"limits": [[None, None]], "text": "Plain X"}]}
    sd = StatDescriptions(support=support, skill=skill)
    assert sd.text("x", 1, is_support=True) == "Supported Skills: X"
    assert sd.text("x", 1, is_support=False) == "Plain X"


def test_scope_falls_back_to_other():
    sd = StatDescriptions(support={"only_skill": _parsed()["reduce_fire_res"]}, skill={})
    # requested as a skill, but the line only exists in the support scope
    assert sd.text("only_skill", 30, is_support=False) == "Penetrate 30% Fire Resistance"


def test_boolean_flag_value_renders_no_gate_line():
    sd = StatDescriptions(support={}, skill={
        "flag": [{"limits": [[None, None]], "text": "Cannot be Frozen"}]})
    assert sd.text("flag", True, is_support=False) == "Cannot be Frozen"


def test_missing_id_returns_none():
    sd = StatDescriptions(support={}, skill={})
    assert sd.text("nope", 1, is_support=False) is None
