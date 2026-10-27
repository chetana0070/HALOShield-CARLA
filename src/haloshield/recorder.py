from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np


class VideoRecorder:
    def __init__(self, path: Path, width: int, height: int, fps: int, prefer_nvenc: bool = True, crf: int = 27) -> None:
        self.path = path
        self.width = width
        self.height = height
        self.fps = fps
        self.crf = crf
        self.process: subprocess.Popen | None = None
        self.encoder = self._select_encoder(prefer_nvenc)
        self.frames_written = 0

    @staticmethod
    def _nvenc_works() -> bool:
        if not shutil.which("ffmpeg"):
            return False
        cmd = [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=size=32x32:rate=1",
            "-frames:v", "1", "-c:v", "h264_nvenc", "-f", "null", "-",
        ]
        try:
            return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8).returncode == 0
        except Exception:
            return False

    def _select_encoder(self, prefer_nvenc: bool) -> str:
        if prefer_nvenc and self._nvenc_works():
            return "h264_nvenc"
        return "libx264"

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{self.width}x{self.height}", "-r", str(self.fps),
            "-i", "-", "-an",
        ]
        if self.encoder == "h264_nvenc":
            cmd += ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq", "-cq", str(self.crf)]
        else:
            cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", str(self.crf)]
        cmd += ["-pix_fmt", "yuv420p", str(self.path)]
        self.process = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def write(self, frame_rgb: np.ndarray) -> None:
        if self.process is None:
            self.start()
        if self.process.poll() is not None:
            raise RuntimeError(f"ffmpeg exited early with code {self.process.returncode}")
        contiguous = np.ascontiguousarray(frame_rgb, dtype=np.uint8)
        assert self.process.stdin is not None
        self.process.stdin.write(contiguous.tobytes())
        self.frames_written += 1

    def close(self) -> None:
        if self.process is None:
            return
        if self.process.stdin:
            try:
                self.process.stdin.close()
            except BrokenPipeError:
                pass
        try:
            self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        if self.process.returncode not in (0, None):
            raise RuntimeError(f"ffmpeg failed with exit code {self.process.returncode}")
