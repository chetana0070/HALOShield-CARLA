from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


@dataclass
class Dashboard:
    width: int
    height: int
    headless: bool = False

    def __post_init__(self) -> None:
        self._pygame = None
        self._screen = None
        self._font = ImageFont.load_default()
        if not self.headless:
            try:
                import pygame
                pygame.init()
                self._pygame = pygame
                self._screen = pygame.display.set_mode((self.width, self.height))
                pygame.display.set_caption("HALOShield-CARLA | Runtime Safety Evidence")
            except Exception:
                self.headless = True

    def render(self, frame_rgb: np.ndarray, hud: dict[str, Any]) -> tuple[np.ndarray, bool]:
        image = Image.fromarray(frame_rgb, mode="RGB")
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.rounded_rectangle((18, 18, 430, 222), radius=12, fill=(8, 12, 20, 190), outline=(220, 220, 220, 120), width=1)
        risk = str(hud.get("risk_level", "CLEAR"))
        lines = [
            f"HALOShield-CARLA   {hud.get('mode', 'shield').upper()}",
            f"Time       {hud.get('elapsed_s', 0.0):6.1f} / {hud.get('duration_s', 120.0):.0f} s",
            f"Speed      {hud.get('speed_mps', 0.0) * 3.6:6.1f} km/h",
            f"Safety     {risk}",
            f"TTC        {self._fmt(hud.get('min_ttc_s'))} s",
            f"Clearance  {self._fmt(hud.get('min_predicted_clearance_m'))} m",
            f"Intervene  {'YES' if hud.get('intervention') else 'no'}",
            f"Seed       {hud.get('seed')}",
            f"Scenario   {hud.get('scenario_phase', 'nominal')}",
        ]
        y = 32
        for idx, line in enumerate(lines):
            fill = (255, 210, 90, 255) if idx == 3 and risk in {"WARNING", "CRITICAL", "HOLD"} else (238, 242, 248, 255)
            draw.text((34, y), line, font=self._font, fill=fill)
            y += 20
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
        array = np.asarray(image)

        keep_running = True
        if not self.headless and self._pygame and self._screen:
            for event in self._pygame.event.get():
                if event.type == self._pygame.QUIT:
                    keep_running = False
            surface = self._pygame.surfarray.make_surface(np.transpose(array, (1, 0, 2)))
            self._screen.blit(surface, (0, 0))
            self._pygame.display.flip()
        return array, keep_running

    @staticmethod
    def _fmt(value: Any) -> str:
        return "--" if value is None else f"{float(value):.2f}"

    def close(self) -> None:
        if self._pygame:
            self._pygame.quit()
