import pytest

from detector.strategy import SetupSpec, all_setups, clear, register


def setup_function():
    clear()


def test_register_and_list():
    spec = SetupSpec(name="dummy", scan=lambda tf: None, killzone_mode="agnostic")
    register(spec)
    assert [item.name for item in all_setups()] == ["dummy"]


def test_register_duplicate_raises():
    spec = SetupSpec(name="dup", scan=lambda tf: None, killzone_mode="agnostic")
    register(spec)
    with pytest.raises(ValueError):
        register(spec)


def test_required_without_killzones_raises():
    with pytest.raises(ValueError):
        register(SetupSpec(name="bad", scan=lambda tf: None,
                           killzone_mode="required", killzones=()))


def test_required_with_killzones_ok():
    register(SetupSpec(name="ok", scan=lambda tf: None,
                       killzone_mode="required", killzones=("LONDON",)))
    assert all_setups()[0].killzones == ("LONDON",)
