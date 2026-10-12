"""Open a window immediately, then load the science libraries behind the animation.

The packaged app also shows splash.png while Windows unpacks the exe. This
window takes over as soon as Python is running, so the wait has a clock.
"""

from __future__ import annotations

import math
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

os.environ.setdefault("MPLBACKEND", "Agg")


class LaunchWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.running = True
        self.phase = 0.0
        self.started = time.monotonic()
        self._after = None
        self.root.title("FickLab")
        self.root.configure(bg="#0f172a")
        self.root.resizable(False, False)
        width, height = 760, 460
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.canvas = tk.Canvas(self.root, width=width, height=height, bg="#0f172a", highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.root.attributes("-topmost", True)
        self._tick()

    def stop(self) -> None:
        self.running = False
        if self._after is not None:
            try:
                self.root.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def _message(self, elapsed: float) -> tuple[str, str]:
        if elapsed < 2:
            return "Opening FickLab", "The window is up. The fitting libraries load next."
        if elapsed < 8:
            return "Loading the fitting libraries", "NumPy, SciPy, and the chart tools are starting."
        return "Still starting", "The first open unpacks a full science stack. The clock means it is working."

    def _tick(self) -> None:
        if not self.running or not self.root.winfo_exists():
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
        left, right = 72.0, width - 72.0
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
        canvas.create_text(width / 2, 148, text=f"{int(elapsed // 60)}:{int(elapsed % 60):02d}", fill="#2dd4bf", font=("Segoe UI", 14, "bold"))
        track_y = height - 36
        canvas.create_line(left, track_y, right, track_y, fill="#1e293b", width=5, capstyle="round")
        span = (right - left) * 0.28
        travel = max(0.0, right - left - span)
        start = left + (0.5 + 0.5 * math.sin(phase * 1.35)) * travel
        canvas.create_line(start, track_y, start + span, track_y, fill="#2dd4bf", width=5, capstyle="round")
        self._after = self.root.after(32, self._tick)


def _load_libraries() -> None:
    import numpy  # noqa: F401
    import scipy.optimize  # noqa: F401
    import scipy.special  # noqa: F401
    import matplotlib

    matplotlib.use("Agg")
    import app_version  # noqa: F401
    import scenario1  # noqa: F401
    import scenario2  # noqa: F401
    import scenario3  # noqa: F401
    import updater  # noqa: F401


def _close_bootloader_splash() -> None:
    try:
        import pyi_splash
    except ImportError:
        return
    try:
        pyi_splash.update_text("Loading the fitting libraries…")
        pyi_splash.close()
    except Exception:
        pass


def main() -> None:
    root = tk.Tk()
    launch = LaunchWindow(root)
    root.update()
    _close_bootloader_splash()

    errors: list[BaseException] = []

    def worker() -> None:
        try:
            _load_libraries()
        except BaseException as error:  # shown on the Tk thread
            errors.append(error)

    thread = threading.Thread(target=worker, name="ficklab-startup", daemon=True)
    thread.start()

    def finish_startup() -> None:
        if thread.is_alive():
            root.after(40, finish_startup)
            return
        launch.stop()
        if errors:
            messagebox.showerror("FickLab could not start", str(errors[0]), parent=root)
            root.destroy()
            return
        import matplotlib

        matplotlib.use("TkAgg", force=True)
        import diffusion_app

        launch.canvas.destroy()
        root.attributes("-topmost", False)
        root.resizable(True, True)
        diffusion_app.DiffusionApp(root)

    root.after(40, finish_startup)
    root.mainloop()


if __name__ == "__main__":
    main()
