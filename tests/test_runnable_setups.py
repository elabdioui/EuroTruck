from detector.strategy import SetupSpec, clear, register, runnable_setups


def setup_function():
    clear()


def _names(active_kz):
    return sorted(spec.name for spec in runnable_setups(active_kz))


def test_required_skipped_outside_killzone():
    register(SetupSpec(
        name="req",
        scan=lambda tf: None,
        killzone_mode="required",
        killzones=("LONDON",),
    ))
    assert _names(None) == []
    assert _names("NY_AM") == []
    assert _names("LONDON") == ["req"]


def test_preferred_runs_only_in_configured_killzone():
    register(SetupSpec(
        name="pref",
        scan=lambda tf: None,
        killzone_mode="preferred",
        killzones=("LONDON", "NY_AM"),
    ))
    assert _names(None) == []
    assert _names("LONDON") == ["pref"]
    assert _names("NY_PM") == []


def test_agnostic_runs_in_any_active_killzone():
    register(SetupSpec(
        name="agn",
        scan=lambda tf: None,
        killzone_mode="agnostic",
    ))
    assert _names(None) == []
    assert _names("NY_PM") == ["agn"]


def test_mixed_outside_killzone_keeps_only_non_required():
    register(SetupSpec(
        name="req",
        scan=lambda tf: None,
        killzone_mode="required",
        killzones=("LONDON",),
    ))
    register(SetupSpec(
        name="pref",
        scan=lambda tf: None,
        killzone_mode="preferred",
        killzones=("LONDON", "NY_AM"),
    ))
    register(SetupSpec(
        name="agn",
        scan=lambda tf: None,
        killzone_mode="agnostic",
    ))
    assert _names(None) == []
    assert _names("LONDON") == ["agn", "pref", "req"]
