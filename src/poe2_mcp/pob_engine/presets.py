"""
Named config-override presets for recompute_stats / compare_dps.

Keys are PoB `<Config>` input names (from Modules/ConfigOptions.lua). Discover a
build's currently-set inputs with the get_config tool; pass arbitrary overrides to
recompute_stats directly. These presets cover the common "what's my real combat DPS"
question for charge/ailment builds, whose exports usually save an unbuffed config.
"""

PRESETS: dict[str, dict] = {
    # The build's saved assumptions, unchanged.
    "unbuffed": {},
    # Assume charge generation is online.
    "charges": {
        "usePowerCharges": True,
        "useFrenzyCharges": True,
    },
    # Enemy is shocked (takes increased damage).
    "shocked": {
        "conditionEnemyShocked": True,
    },
    # Full offensive scenario: charges up, enemy shocked, recent crit / charge gained.
    "combat": {
        "usePowerCharges": True,
        "useFrenzyCharges": True,
        "conditionEnemyShocked": True,
        "conditionGainedPowerChargeRecently": True,
        "conditionCritRecently": True,
    },
}
