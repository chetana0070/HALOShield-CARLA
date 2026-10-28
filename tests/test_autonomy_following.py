from haloshield.autonomy import AdaptiveCruiseSupervisor
from haloshield.config import load_config
from haloshield.types import (
    ActorState,
    EgoState,
    NominalControl,
    Vec2,
)


def ego(speed=8.0):
    return EgoState(
        position=Vec2(0, 0),
        velocity=Vec2(speed, 0),
        forward=Vec2(1, 0),
        right=Vec2(0, 1),
        half_length=2.2,
        half_width=1.0,
        speed_mps=speed,
    )


def actor(
    x,
    speed=8.0,
    y=0.0,
    actor_id=7,
):
    return ActorState(
        actor_id,
        "vehicle.test",
        Vec2(x, y),
        Vec2(speed, 0),
        2.2,
        1.0,
    )


def supervisor():
    return AdaptiveCruiseSupervisor(
        load_config()["controller"]
    )


def test_distant_lead_does_not_modify_control():
    nominal = NominalControl(
        0.5,
        0.0,
        0.1,
    )

    control, status = supervisor().apply(
        nominal,
        ego(),
        [actor(50)],
    )

    assert control == nominal
    assert status.active is False


def test_close_slow_lead_uses_nominal_following():
    nominal = NominalControl(
        0.6,
        0.0,
        0.0,
    )

    control, status = supervisor().apply(
        nominal,
        ego(),
        [actor(14, speed=2.0)],
    )

    assert status.active is True
    assert control.throttle == 0.0
    assert control.brake > 0.0


def test_adjacent_lane_vehicle_is_ignored():
    nominal = NominalControl(
        0.6,
        0.0,
        0.0,
    )

    control, status = supervisor().apply(
        nominal,
        ego(),
        [actor(10, speed=0.0, y=6.0)],
    )

    assert control == nominal
    assert status.active is False
