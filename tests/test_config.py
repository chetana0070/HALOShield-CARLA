from haloshield.config import load_config


def test_default_config_loads():
    cfg = load_config()
    assert cfg["experiment"]["duration_s"] == 120.0
    assert cfg["experiment"]["mode"] == "shield"


def test_override_is_applied_without_mutating_file():
    cfg = load_config(overrides={"experiment": {"duration_s": 12.5}})
    assert cfg["experiment"]["duration_s"] == 12.5
    again = load_config()
    assert again["experiment"]["duration_s"] == 120.0
