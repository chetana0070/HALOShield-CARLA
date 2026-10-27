from haloshield.metrics import MetricsCollector


def test_metrics_summary_counts_intervention_events_and_distance():
    m = MetricsCollector()
    rows = [
        {"speed_mps": 2.0, "intervention": False, "min_ttc_s": 3.0, "min_predicted_clearance_m": 2.0, "safety_latency_ms": 0.1},
        {"speed_mps": 3.0, "intervention": True, "min_ttc_s": 1.0, "min_predicted_clearance_m": 0.5, "safety_latency_ms": 0.2},
        {"speed_mps": 2.5, "intervention": True, "min_ttc_s": 0.8, "min_predicted_clearance_m": 0.2, "safety_latency_ms": 0.15},
        {"speed_mps": 2.0, "intervention": False, "min_ttc_s": None, "min_predicted_clearance_m": None, "safety_latency_ms": 0.1},
    ]
    locations = [(0, 0, 0), (3, 4, 0), (6, 8, 0), (6, 8, 0)]
    for row, loc in zip(rows, locations):
        m.record_tick(row, loc)
    summary = m.summary(0.2, "completed")
    assert summary["intervention_events"] == 1
    assert summary["distance_m"] == 10.0
    assert summary["min_ttc_s"] == 0.8
