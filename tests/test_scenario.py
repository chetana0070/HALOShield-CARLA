from haloshield.config import load_config
from haloshield.scenario import generate_scenario, scenario_from_dict


def test_scenario_generation_is_seed_reproducible():
    cfg = load_config()
    maps = ["/Game/Carla/Maps/Town01", "/Game/Carla/Maps/Town03"]
    a = generate_scenario(1234, cfg, maps)
    b = generate_scenario(1234, cfg, maps)
    assert a.to_dict() == b.to_dict()


def test_different_seeds_change_scenario():
    cfg = load_config()
    maps = ["/Game/Carla/Maps/Town01", "/Game/Carla/Maps/Town03"]
    assert generate_scenario(1, cfg, maps).to_dict() != generate_scenario(2, cfg, maps).to_dict()


def test_scenario_roundtrip():
    cfg = load_config()
    original = generate_scenario(42, cfg, ["/Game/Carla/Maps/Town03"])
    restored = scenario_from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()
