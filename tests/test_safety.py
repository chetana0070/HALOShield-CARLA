from haloshield.config import load_config
from haloshield.safety import PredictiveSafetyShield, SafetyConfig
from haloshield.types import ActorState, EgoState, NominalControl, Vec2


def make_shield():
    cfg = load_config()
    return PredictiveSafetyShield(SafetyConfig.from_mapping(cfg["safety"]))


def ego(speed=10.0):
    return EgoState(
        position=Vec2(0, 0), velocity=Vec2(speed, 0), forward=Vec2(1, 0), right=Vec2(0, 1),
        half_length=2.2, half_width=1.0, speed_mps=speed,
    )


def actor(x, speed=0.0, y=0.0):
    return ActorState(7, "vehicle.test", Vec2(x, y), Vec2(speed, 0), 2.2, 1.0)


def test_clear_actor_does_not_intervene():
    shield = make_shield()
    decision = shield.evaluate(ego(), [actor(50, speed=10)], 0.0)
    assert decision.intervention is False


def test_close_stopped_vehicle_triggers_braking():
    shield = make_shield()
    decision = shield.evaluate(ego(), [actor(10, speed=0)], 0.0)
    assert decision.intervention is True
    applied = shield.apply(NominalControl(0.6, 0.0, 0.1), decision, enabled=True)
    assert applied.throttle == 0.0
    assert applied.brake > 0.0


def test_baseline_mode_can_ignore_override():
    shield = make_shield()
    decision = shield.evaluate(ego(), [actor(10)], 0.0)
    nominal = NominalControl(0.5, 0.0, -0.1)
    applied = shield.apply(nominal, decision, enabled=False)
    assert applied == nominal


def test_lateral_actor_outside_corridor_is_ignored():
    shield = make_shield()
    decision = shield.evaluate(ego(), [actor(8, speed=0, y=12)], 0.0)
    assert decision.intervention is False
