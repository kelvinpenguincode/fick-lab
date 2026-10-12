"""Animated FickLab window shown while the app starts or installs an update."""

from __future__ import annotations

import math
import time
import tkinter as tk


class SplashWindow:
    def __init__(self, window: tk.Misc, kind: str = "launch") -> None:
        self.window = window
        self.kind = kind
        self.running = True
        self.phase = 0.0
        self.started = time.monotonic()
        self._after = None
        self._title = ""
        self._detail = ""
        self.progress: float | None = None
        window.title("FickLab")
        window.configure(bg="#0f172a")
        try:
            window.resizable(False, False)
        except tk.TclError:
            pass
        width, height = 760, 460
        screen_w = window.winfo_screenwidth()
        screen_h = window.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        window.geometry(f"{width}x{height}+{x}+{y}")
        self.canvas = tk.Canvas(window, width=width, height=height, bg="#0f172a", highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        try:
            window.attributes("-topmost", True)
        except tk.TclError:
            pass
        if isinstance(window, tk.Toplevel):
            window.protocol("WM_DELETE_WINDOW", lambda: None)
        self._tick()

    def set_status(self, title: str, detail: str) -> None:
        self._title = title
        self._detail = detail

    def set_progress(self, fraction: float | None) -> None:
        if fraction is None:
            self.progress = None
            return
        self.progress = max(0.0, min(1.0, fraction))

    def close(self) -> None:
        self.running = False
        if self._after is not None:
            try:
                self.window.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        try:
            self.window.attributes("-topmost", False)
        except tk.TclError:
            pass
        if isinstance(self.window, tk.Toplevel):
            self.window.destroy()
        elif self.canvas.winfo_exists():
            self.canvas.destroy()

    def _message(self, elapsed: float) -> tuple[str, str]:
        if self._title:
            return self._title, self._detail
        if self.kind == "install":
            return "Adding FickLab to the Start menu", "The shortcut always opens the latest installed copy."
        if self.kind == "update":
            return "Downloading the update", "FickLab restarts itself when the new version is ready."
        if elapsed < 2:
            return "Opening FickLab", "The window is up. The fitting libraries load next."
        if elapsed < 8:
            return "Loading the fitting libraries", "NumPy, SciPy, and the chart tools are starting."
        return "Still starting", "The first open unpacks a full science stack. The clock means it is working."

    def _tick(self) -> None:
        if not self.running:
            return
        try:
            if not self.window.winfo_exists():
                return
        except tk.TclError:
            return
        canvas = self.canvas
        width = max(canvas.winfo_width(), 760)
        height = max(canvas.winfo_height(), 460)
        canvas.delete("all")
        self.phase += 0.05
        phase = self.phase
        for index in range(1, 5):
            line_y = 150 + (height - 230) * index / 5
            canvas.create_line(72, line_y, width - 72, line_y, fill="#1e293b")
        spread = 0.16 + 0.2 * (0.5 + 0.5 * math.sin(phase * 0.65))
        steps = 90
        left, right = 72.0, float(width - 72)
        base = height * 0.72
        amplitude = height * 0.24
        coordinates: list[float] = []
        for index in range(steps):
            fraction = index / (steps - 1)
            height_fraction = math.erfc(fraction / (2.0 * spread))
            coordinates.extend((left + fraction * (right - left), base - height_fraction * amplitude))
        canvas.create_line(*coordinates, fill="#2dd4bf", width=3, smooth=True, capstyle="round")
        bead = int((0.15 + 0.7 * (0.5 + 0.5 * math.sin(phase))) * (steps - 1))
        bead_x = coordinates[bead * 2]
        bead_y = coordinates[bead * 2 + 1]
        glow = 11 + 3 * math.sin(phase * 2.2)
        canvas.create_oval(bead_x - glow, bead_y - glow, bead_x + glow, bead_y + glow, outline="#2dd4bf", width=2)
        canvas.create_oval(bead_x - 4.5, bead_y - 4.5, bead_x + 4.5, bead_y + 4.5, fill="#99f6e4", outline="")
        elapsed = max(0.0, time.monotonic() - self.started)
        title, detail = self._message(elapsed)
        canvas.create_text(width / 2, 48, text="FickLab", fill="#f8fafc", font=("Segoe UI", 26, "bold"))
        canvas.create_text(width / 2, 86, text=title, fill="#f8fafc", font=("Segoe UI", 16, "bold"))
        canvas.create_text(width / 2, 116, text=detail, fill="#94a3b8", font=("Segoe UI", 11), width=width - 120)
        if self.kind == "launch":
            canvas.create_text(
                width / 2, 148, text=f"{int(elapsed // 60)}:{int(elapsed % 60):02d}", fill="#2dd4bf", font=("Segoe UI", 14, "bold")
            )
        elif self.progress is not None:
            canvas.create_text(width / 2, 148, text=f"{self.progress * 100:.0f}%", fill="#2dd4bf", font=("Segoe UI", 14, "bold"))
        else:
            canvas.create_text(
                width / 2, 148, text=f"{int(elapsed // 60)}:{int(elapsed % 60):02d}", fill="#2dd4bf", font=("Segoe UI", 14, "bold")
            )
        track_y = height - 36
        canvas.create_line(left, track_y, right, track_y, fill="#1e293b", width=5, capstyle="round")
        if self.progress is None:
            span = (right - left) * 0.28
            travel = max(0.0, right - left - span)
            start = left + (0.5 + 0.5 * math.sin(phase * 1.35)) * travel
            canvas.create_line(start, track_y, start + span, track_y, fill="#2dd4bf", width=5, capstyle="round")
        else:
            filled = left + (right - left) * self.progress
            canvas.create_line(left, track_y, filled, track_y, fill="#2dd4bf", width=5, capstyle="round")
        self._after = self.window.after(32, self._tick)
