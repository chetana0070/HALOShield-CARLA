# Research specification: HALOShield-CARLA

## Abstract

HALOShield-CARLA studies whether a computationally inexpensive runtime safety layer can improve closed-loop autonomous-driving safety under randomized interactions without requiring a large learned model or specialized automotive compute. The proposed Uncertainty-aware Predictive Runtime Shield (U-PRS) monitors nearby dynamic actors, performs multi-horizon constant-velocity projection, expands safety envelopes with time-dependent uncertainty, and can independently constrain nominal control. CARLA supplies randomized closed-loop scenarios; paired seeds allow direct baseline-versus-shield evaluation. The project produces traceable scenario, decision, intervention, outcome, performance, and resource evidence. No experimental improvement is claimed until benchmark runs are executed.

## 1. Introduction

Modern autonomous-driving stacks can produce a plausible action while still requiring an independent mechanism to decide whether that action remains safe under uncertain near-term interactions. Full production safety systems are complex and hardware-specific; research often needs a smaller mechanism whose assumptions and decisions can be audited. HALOShield-CARLA isolates that problem in a reproducible simulator experiment.

## 2. Motivation

Safety research needs more than collision counts. A useful experiment should connect what the system observed to what it predicted, why it intervened, what control was applied, and what outcome followed. This repository treats those links as first-class evidence rather than logging added after the fact.

## 3. Research gap

Many educational CARLA demonstrations either use Traffic Manager autopilot as a black box or focus on perception/model accuracy without an independent runtime safety contract. Conversely, production-grade safety platforms are not generally deployable on a student laptop. The gap addressed here is a transparent, measurable, resource-constrained runtime shield with paired scenario evaluation.

## 4. Research question

Can an uncertainty-inflated short-horizon predictive runtime shield reduce collision exposure and critical TTC conditions in randomized CARLA driving while preserving useful progress on an 8 GB GPU laptop?

## 5. Hypothesis

Across paired scenario seeds, U-PRS is expected to reduce collisions and time spent in critical TTC states relative to the same nominal controller with monitoring-only baseline, at the cost of some braking interventions and potentially modest loss of distance or mean speed. This is a hypothesis, not a measured result.

## 6. Related concepts

The architecture uses ideas common to runtime assurance, safety cages/shields, time-to-collision analysis, forward reachable approximations, uncertainty inflation, scenario-based validation, and safety evidence pipelines. NVIDIA Halos SAFE is a public conceptual reference for scenario/KPI/evidence-oriented validation; this repository does not implement proprietary Halos software.

## 7. Proposed method

At each control cycle:

1. Nominal autonomy proposes throttle, brake, and steer.
2. Nearby vehicles and pedestrians are projected over horizons from 0.5 to 3.0 seconds under constant velocity.
3. A geometric safety envelope is inflated as `u(h) = u0 + growth * h`.
4. The minimum predicted clearance and longitudinal TTC are computed.
5. Risk is mapped to CLEAR, CAUTION, WARNING, or CRITICAL.
6. CAUTION caps throttle; WARNING/CRITICAL can override braking.
7. Hysteresis briefly holds an intervention to avoid control chatter.
8. Every decision and outcome is logged.

The constant-velocity predictor is intentionally simple. That makes its failure modes auditable and creates a clean research path for replacing it with learned or interaction-aware predictors in future ablations.

## 8. System architecture

Nominal control and safety control are independent modules. The safety module never chooses the route; it only evaluates risk and restricts the proposed action. This separation makes `baseline` and `shield` modes comparable.

## 9. Experimental setup

Default run duration is 120 simulated seconds at 20 Hz physics (`fixed_delta_seconds=0.05`). RGB evidence is recorded at 10 FPS and 960×540. Maps are selected from smaller packaged CARLA towns when available. Each run includes background traffic, pedestrians, a scripted lead vehicle, randomized weather, and two seeded lead hard-braking events.

## 10. Baseline

`--mode baseline` uses identical scenario generation and nominal control but does not apply the safety shield's throttle/brake constraints. Risk is still computed so exposure can be compared consistently.

## 11. Metrics

Primary safety metrics:
- collisions;
- minimum TTC;
- minimum predicted clearance;
- critical/near-miss exposure;
- safety intervention events.

Utility metrics:
- distance traveled;
- mean speed.

Systems metrics:
- safety-layer latency;
- wall-clock runtime;
- recorded resource context.

## 12. Evaluation protocol

Use paired seeds. For seed `s`, run baseline and shield with the same `scenario.json` parameters. Aggregate differences per pair before population-level claims. The included benchmark script automates paired runs and descriptive summaries.

## 13. Ablation studies

Recommended ablations already supported by configuration:
- disable shield (`baseline`);
- reduce/expand prediction horizon;
- remove uncertainty growth by setting it to zero;
- alter TTC thresholds;
- alter clearance thresholds;
- alter intervention hold time;
- vary traffic density.

## 14. Failure analysis

Important failures include collision despite intervention, false-positive braking with large clearance, repeated stop-and-go due to hysteresis, controller departure from the intended corridor, CARLA simulation stalls, high safety latency, and hazard scenarios in which the scripted lead no longer remains relevant. Telemetry and event logs should be inspected before attributing causality.

## 15. Limitations

- The predictor assumes constant actor velocity over a short horizon.
- Bounding envelopes are simplified 2D approximations.
- The nominal autonomy stack is intentionally lightweight.
- The scripted lead-brake hazard is not a complete representation of real traffic behavior.
- CARLA simulation fidelity does not establish real-world safety.
- Ubuntu 24.04 is outside the officially stated 0.9.16 OS list even though the project uses the packaged binary to avoid source-build incompatibility.

## 16. Threats to validity

Scenario diversity may be insufficient; simulator physics may bias results; the chosen TTC/clearance thresholds may favor one mode; hazard timing can interact with intersections; background Traffic Manager behavior can vary with simulator implementation; and repeated runs may still cover only a small operational domain.

## 17. Future research

Potential extensions include interaction-aware trajectory prediction, conformal uncertainty calibration, responsibility-sensitive safety constraints, control barrier functions, reachability libraries, learned intent prediction, adversarial scenario generation, coverage-guided scenario search, and transfer to a genuine safety-certified automotive platform where available.

## 18. Reproducibility

Every run stores the seed, scenario parameters, configuration snapshot, software/system context, telemetry, events, and output metrics. `--replay scenario.json` reconstructs the saved scenario contract. Use source-control commit hashes for paper experiments.
