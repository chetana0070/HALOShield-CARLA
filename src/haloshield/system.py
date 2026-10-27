from __future__ import annotations

import importlib.util
import importlib.metadata
import os
import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import psutil


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""



def _run(cmd: list[str]) -> str | None:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
    except Exception:
        return None


def gpu_info() -> dict[str, Any]:
    query = _run([
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.free,driver_version",
        "--format=csv,noheader,nounits",
    ])
    if not query:
        return {"available": False}
    first = query.splitlines()[0]
    parts = [part.strip() for part in first.split(",")]
    if len(parts) < 4:
        return {"available": False, "raw": first}
    return {
        "available": True,
        "name": parts[0],
        "memory_total_mib": float(parts[1]),
        "memory_free_mib": float(parts[2]),
        "driver_version": parts[3],
    }


def cuda_info() -> dict[str, Any]:
    nvcc = _run(["nvcc", "--version"])
    return {"nvcc": nvcc, "visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", "default")}


def disk_free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / (1024 ** 3)


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def carla_root() -> Path | None:
    candidates: list[Path] = []
    env = os.environ.get("CARLA_ROOT")
    if env:
        candidates.append(Path(env).expanduser())
    home = Path.home()
    candidates.extend([
        home / ".cache" / "haloshield" / "CARLA_0.9.16",
        home / "CARLA_0.9.16",
        home / "carla" / "0.9.16",
        Path("/opt/carla/0.9.16"),
    ])
    for candidate in candidates:
        if (candidate / "CarlaUE4.sh").exists():
            return candidate.resolve()
    return None


def collect_system_info(workdir: Path) -> dict[str, Any]:
    memory = psutil.virtual_memory()
    versions = {}
    for package in ("numpy", "PyYAML", "psutil", "Pillow", "pygame", "matplotlib", "carla"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return {
        "platform": platform.platform(),
        "python": sys.version,
        "dependency_versions": versions,
        "cpu_logical": psutil.cpu_count(logical=True),
        "cpu_physical": psutil.cpu_count(logical=False),
        "ram_total_gib": round(memory.total / 1024 ** 3, 2),
        "ram_available_gib": round(memory.available / 1024 ** 3, 2),
        "disk_free_gib": round(disk_free_gb(workdir), 2),
        "gpu": gpu_info(),
        "cuda": cuda_info(),
        "carla_root": str(carla_root()) if carla_root() else None,
    }


def doctor(project_root: Path, host: str = "127.0.0.1", port: int = 2000) -> list[Check]:
    checks: list[Check] = []
    release = platform.release()
    os_ok = platform.system() == "Linux"
    checks.append(Check("OS", "PASS" if os_ok else "FAIL", platform.platform(), "Use Ubuntu Linux." if not os_ok else ""))

    gpu = gpu_info()
    if gpu.get("available"):
        vram = float(gpu.get("memory_total_mib", 0))
        checks.append(Check("NVIDIA GPU", "PASS", f"{gpu.get('name')} / driver {gpu.get('driver_version')}"))
        checks.append(Check("VRAM", "PASS" if vram >= 7800 else "WARN", f"{vram:.0f} MiB", "Use the low preset and reduce camera/NPC load." if vram < 7800 else ""))
    else:
        checks.append(Check("NVIDIA GPU", "FAIL", "nvidia-smi unavailable", "Install/repair the NVIDIA driver before running CARLA."))
        checks.append(Check("VRAM", "FAIL", "unknown"))

    py_ok = (3, 10) <= sys.version_info[:2] <= (3, 12)
    checks.append(Check("Python", "PASS" if py_ok else "FAIL", sys.version.split()[0], "Use Python 3.10-3.12." if not py_ok else ""))

    root = carla_root()
    checks.append(Check("CARLA", "PASS" if root else "WARN", str(root) if root else "CARLA 0.9.16 not found", "Normal ./run_project.sh will install the packaged CARLA 0.9.16 build." if not root else ""))
    checks.append(Check("Port 2000", "WARN" if port_in_use(host, port) else "PASS", "in use" if port_in_use(host, port) else "available", "If CARLA is not already running, free port 2000." if port_in_use(host, port) else ""))

    free = disk_free_gb(project_root)
    checks.append(Check("Disk", "PASS" if free >= 4 else "FAIL", f"{free:.1f} GiB free", "Free at least 4 GiB before a run; CARLA installation itself needs much more." if free < 4 else ""))
    checks.append(Check("ffmpeg", "PASS" if shutil.which("ffmpeg") else "FAIL", shutil.which("ffmpeg") or "not found", "sudo apt install ffmpeg" if not shutil.which("ffmpeg") else ""))

    for module in ["numpy", "yaml", "psutil", "PIL"]:
        ok = importlib.util.find_spec(module) is not None
        checks.append(Check(f"Python module: {module}", "PASS" if ok else "FAIL", "installed" if ok else "missing", "Run ./run_project.sh to bootstrap the environment." if not ok else ""))
    return checks


def checks_as_dict(checks: list[Check]) -> list[dict[str, str]]:
    return [asdict(check) for check in checks]
