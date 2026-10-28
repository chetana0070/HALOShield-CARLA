from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from .system import carla_root, port_in_use


def expose_carla_pythonapi(root: Path | None = None) -> None:
    root = root or carla_root()
    if not root:
        return
    agents_path = root / "PythonAPI" / "carla"
    examples_path = root / "PythonAPI" / "examples"
    for path in (agents_path, examples_path):
        if path.exists() and str(path) not in sys.path:
            sys.path.insert(0, str(path))


def import_carla():
    expose_carla_pythonapi()
    try:
        import carla  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "CARLA Python API is unavailable. Re-run ./run_project.sh so bootstrap can install the matching 0.9.16 API."
        ) from exc
    return carla


class CarlaServerManager:
    def __init__(self, cfg: dict, log_path: Path) -> None:
        self.cfg = cfg
        self.log_path = log_path
        self.process: subprocess.Popen | None = None
        self._owns_server = False
        self._server_pgid: int | None = None
        self._log_handle = None

    def start_if_needed(self) -> bool:
        host = str(self.cfg["host"])
        port = int(self.cfg["port"])
        if port_in_use(host, port):
            return False
        root = carla_root()
        if not root:
            raise RuntimeError("CARLA 0.9.16 installation was not found. Run ./run_project.sh without --doctor to install it.")
        launch = root / "CarlaUE4.sh"
        if not launch.exists():
            raise RuntimeError(f"CARLA launcher not found: {launch}")
        cmd = [
            str(launch),
            f"-carla-rpc-port={port}",
            f"-quality-level={self.cfg['quality']}",
            "-ResX=960",
            "-ResY=540",
            "-windowed",
        ]
        if bool(self.cfg.get("offscreen", True)):
            cmd.append("-RenderOffScreen")
        if bool(self.cfg.get("no_sound", True)):
            cmd.append("-nosound")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = self.log_path.open("w", encoding="utf-8")
        env = os.environ.copy()
        env.setdefault("SDL_AUDIODRIVER", "dummy")
        self.process = subprocess.Popen(
            cmd,
            cwd=root,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
        # start_new_session=True makes the initial PID the process-group
        # leader. Preserve that PGID even if CarlaUE4.sh later exits while
        # the Unreal binary remains alive.
        self._server_pgid = self.process.pid
        self._owns_server = True
        return True

    def wait_until_ready(self) -> None:
        host = str(self.cfg["host"])
        port = int(self.cfg["port"])
        timeout_s = float(self.cfg["timeout_s"])
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.process and self.process.poll() is not None:
                raise RuntimeError(
                    f"CARLA exited during startup with code {self.process.returncode}. Inspect {self.log_path}."
                )
            try:
                with socket.create_connection((host, port), timeout=0.5):
                    return
            except OSError:
                time.sleep(1.0)
        raise RuntimeError(
            f"CARLA server did not become ready on {host}:{port} within {timeout_s:.0f}s. Inspect {self.log_path}."
        )

    def stop(self) -> None:
        """Terminate the complete CARLA process group owned by this run."""

        pgid = self._server_pgid

        if self._owns_server and pgid is not None:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                if self.process is not None:
                    try:
                        self.process.terminate()
                    except ProcessLookupError:
                        pass

            # Wait for Unreal to release RPC port 2000, not merely for the
            # shell wrapper process to exit.
            host = str(self.cfg["host"])
            port = int(self.cfg["port"])

            deadline = time.monotonic() + 15.0

            while (
                time.monotonic() < deadline
                and port_in_use(host, port)
            ):
                time.sleep(0.5)

            if port_in_use(host, port):
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    if self.process is not None:
                        try:
                            self.process.kill()
                        except ProcessLookupError:
                            pass

                deadline = time.monotonic() + 5.0

                while (
                    time.monotonic() < deadline
                    and port_in_use(host, port)
                ):
                    time.sleep(0.25)

        if self.process is not None:
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            except ChildProcessError:
                pass

        self.process = None
        self._owns_server = False
        self._server_pgid = None

        if self._log_handle:
            try:
                self._log_handle.close()
            finally:
                self._log_handle = None
