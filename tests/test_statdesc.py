from poe2_mcp.skills.statdesc import (
    parse_stat_descriptions,
    render,
    render_multi,
    StatDescriptions,
    _LuaTableParser,
    _limit_ok,
)


# A compact stat-description table covering the cases that matter: penetration, an
# increased/reduced pair chosen by limit sign, a sign-forced level line, value
# transforms (ms→s, negate, per-minute→per-second, ÷100), a multi-stat line, an
# unrenderable hash handler, and the rare "!" negation bound.
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
        [1]={ [1]={ [1]={k="milliseconds_to_seconds",v=1}, limit={ {"#","#"} },
                    text="Trigger every {0} seconds" } },
        stats={ [1]="trigger_interval_ms" }
    },
    [5]={
        [1]={ [1]={ limit={ {"#","#"},{"#","#"} }, text="Adds {0} to {1} Damage" } },
        stats={ [1]="min_dmg", [2]="max_dmg" }
    },
    [6]={
        [1]={ [1]={ limit={ {"!","#"} }, text="never matches" } },
        stats={ [1]="weird" }
    },
    [7]={
        [1]={ [1]={ [1]={k="negate",v=1}, limit={ {"#",-1} }, text="{0}% less Damage" } },
        stats={ [1]="dmg_final" }
    },
    [8]={
        [1]={ [1]={ [1]={k="per_minute_to_per_second",v=1}, limit={ {"#","#"} },
                    text="Regenerate {0} Life per second" } },
        stats={ [1]="life_regen_per_minute" }
    },
    [9]={
        [1]={ [1]={ [1]={k="divide_by_one_hundred",v=1}, limit={ {"#","#"} },
                    text="{0}% chance" } },
        stats={ [1]="frac_chance" }
    },
    [10]={
        [1]={ [1]={ [1]={k="passive_hash",v=1}, limit={ {"#","#"} }, text="Allocates {0}" } },
        stats={ [1]="hashed_id" }
    }
}
"""


def _parsed():
    return parse_stat_descriptions(SAMPLE)


def _single(sid):
    return _parsed()["single"][sid]


# -- parsing -----------------------------------------------------------------

def test_positional_and_keyed_entries_parse():
    root = _LuaTableParser(SAMPLE).parse_return()
    assert set(root) == {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}


def test_single_and_multi_split():
    p = _parsed()
    assert "reduce_fire_res" in p["single"]
    # the two-id entry lands in multi, keyed by both members
    assert len(p["multi"]) == 1
    assert p["multi"][0]["stats"] == ["min_dmg", "max_dmg"]


def test_transforms_captured_on_variant():
    assert _single("trigger_interval_ms")[0]["transforms"] == {"1": ["milliseconds_to_seconds", 1]}
    assert "transforms" not in _single("reduce_fire_res")[0]


# -- single-stat rendering ---------------------------------------------------

def test_renders_value_into_template():
    assert render(_single("reduce_fire_res"), 30) == "Penetrate 30% Fire Resistance"


def test_limit_selects_increased_vs_reduced():
    v = _single("attack_speed_+%")
    assert render(v, 10) == "10% increased Attack Speed"
    assert render(v, -10) == "-10% reduced Attack Speed"


def test_sign_forcing_format_spec():
    assert render(_single("gem_level_+"), 2) == "+2 to Level of Supported Skills"


def test_no_matching_variant_returns_none():
    assert render(_single("attack_speed_+%"), 0) is None


def test_non_numeric_bound_is_skipped():
    assert render(_single("weird"), 5) is None
    assert _limit_ok(["!", None], 5) is False


# -- value transforms --------------------------------------------------------

def test_milliseconds_to_seconds():
    assert render(_single("trigger_interval_ms"), 3000) == "Trigger every 3 seconds"


def test_negate_shows_positive_with_less_wording():
    assert render(_single("dmg_final"), -30) == "30% less Damage"


def test_per_minute_to_per_second():
    assert render(_single("life_regen_per_minute"), 120) == "Regenerate 2 Life per second"


def test_divide_by_one_hundred():
    assert render(_single("frac_chance"), 50) == "0.5% chance"


def test_unrenderable_handler_returns_none():
    # a hash/index handler we can't resolve must omit the line, not print garbage
    assert render(_single("hashed_id"), 7) is None


# -- multi-stat rendering ----------------------------------------------------

def test_render_multi_combines_siblings():
    entry = _parsed()["multi"][0]
    out = render_multi(entry["stats"], entry["variants"], {"min_dmg": 5, "max_dmg": 12})
    assert out == "Adds 5 to 12 Damage"


def test_render_multi_needs_all_values():
    entry = _parsed()["multi"][0]
    assert render_multi(entry["stats"], entry["variants"], {"min_dmg": 5}) is None


# -- StatDescriptions: scope, list rendering, flags --------------------------

def _sd(**over):
    base = {"single": {}, "multi": []}
    return StatDescriptions(support={**base, **over.get("support", {})},
                            skill={**base, **over.get("skill", {})})


def test_text_single_with_transform():
    sd = _sd(skill={"single": {"trigger_interval_ms": _single("trigger_interval_ms")}})
    assert sd.text("trigger_interval_ms", 3000, is_support=False) == "Trigger every 3 seconds"


def test_ms_suffix_fallback_without_transform():
    # no transform on the variant, but the *_ms id name triggers the ÷1000 fallback
    variants = [{"limits": [[None, None]], "text": "Lasts {0} seconds"}]
    sd = _sd(skill={"single": {"buff_duration_ms": variants}})
    assert sd.text("buff_duration_ms", 2500, is_support=False) == "Lasts 2.5 seconds"


def test_render_stats_attaches_multi_once_and_consumes_siblings():
    p = _parsed()
    sd = StatDescriptions(support={"single": {}, "multi": []},
                          skill={"single": {}, "multi": p["multi"]})
    stats = [{"id": "min_dmg", "value": 5}, {"id": "max_dmg", "value": 12}]
    lines = sd.render_stats(stats, is_support=False)
    assert lines == ["Adds 5 to 12 Damage", None]   # second member consumed


def test_render_stats_scope_preference():
    support = {"single": {"x": [{"limits": [[None, None]], "text": "Supported: X"}]}, "multi": []}
    skill = {"single": {"x": [{"limits": [[None, None]], "text": "Plain X"}]}, "multi": []}
    sd = StatDescriptions(support=support, skill=skill)
    assert sd.render_stats([{"id": "x", "value": 1}], is_support=True) == ["Supported: X"]
    assert sd.render_stats([{"id": "x", "value": 1}], is_support=False) == ["Plain X"]


def test_quality_stats_render_at_20_percent():
    # a per-1%-quality value of 0.1 is shown at the 20% cap (2), tagged accordingly
    variants = [{"limits": [[1, None]], "text": "Chain +{0} times"}]
    sd = _sd(skill={"single": {"number_of_chains": variants}})
    stats = [{"id": "number_of_chains", "value": 0.1}]
    assert sd.render_stats(stats, is_support=False, quality=True) == [
        "Chain +2 times (at 20% quality)"]
    # and float noise from the *20 scaling is rounded away (no "2.0000000004")
    assert "2.0" not in sd.render_stats(stats, is_support=False, quality=True)[0]


def test_quality_off_is_unscaled():
    variants = [{"limits": [[1, None]], "text": "Chain +{0} times"}]
    sd = _sd(skill={"single": {"number_of_chains": variants}})
    stats = [{"id": "number_of_chains", "value": 2}]
    assert sd.render_stats(stats, is_support=False) == ["Chain +2 times"]


def test_boolean_flag_value_renders_no_gate_line():
    sd = _sd(skill={"single": {"flag": [{"limits": [[None, None]], "text": "Cannot be Frozen"}]}})
    assert sd.text("flag", True, is_support=False) == "Cannot be Frozen"


def test_missing_id_returns_none():
    assert _sd().text("nope", 1, is_support=False) is None
