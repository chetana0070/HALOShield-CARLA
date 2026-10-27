# NVIDIA Halos mapping and boundary

## Public conceptual mapping

NVIDIA's public autonomous-vehicle Halos material describes safety across platform, OS, algorithms, evaluation, and inspection. It describes Halos SAFE as an AV safety evaluation framework combining simulation/testing and traceable evidence.

HALOShield-CARLA maps only to public concepts:

| Public safety concept | Research implementation |
|---|---|
| independent safety check | U-PRS risk monitor separate from nominal controller |
| repeatable scenario | seed + serialized `scenario.json` |
| KPI/evaluation | TTC, clearance, collision, progress, intervention and latency metrics |
| traceable evidence | telemetry, event log, configuration, system context, video, report |
| lifecycle boundary | simulation-only warning and explicit non-certification |

## What is not included

- NVIDIA Halos OS
- Halos Core
- NVIDIA DRIVE OS
- DRIVE AGX hardware
- NVIDIA Hyperion hardware
- any confidential NVIDIA interface
- any certification artifact

The phrase "Halos-inspired" in this repository means architectural inspiration from public documentation, not binary compatibility or certification.

Public source: https://www.nvidia.com/en-us/ai-trust-center/halos/autonomous-vehicles/
