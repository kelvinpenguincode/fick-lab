"""Open a window immediately, then load the science libraries behind the animation.

The packaged app also shows splash.png while Windows unpacks the exe. This
window takes over as soon as Python is running, so the wait has a clock.
A downloaded copy hands off to the Start-menu install so an update is the
copy that actually opens.
"""

from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox

import updater
from splash_window import SplashWindow

os.environ.setdefault("MPLBACKEND", "Agg")


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
    import arrhenius  # noqa: F401


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


def _handoff_to_install(root: tk.Tk) -> bool:
    """Copy this exe into the Start-menu install when that copy should be the one running.

    Returns True when this process should stop because the installed copy was started.
    """
    if not updater.should_handoff():
        threading.Thread(target=updater.remember_install, name="ficklab-shortcuts", daemon=True).start()
        return False
    splash = SplashWindow(root, "install")
    root.update()
    _close_bootloader_splash()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            updater.publish_installed_copy()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=worker, name="ficklab-install", daemon=True)
    thread.start()
    handed_off: list[bool] = []

    def finish() -> None:
        if thread.is_alive():
            root.after(40, finish)
            return
        splash.close()
        if errors:
            messagebox.showerror(
                "FickLab",
                "FickLab could not add the Start menu shortcut, so this copy will open instead.\n\n" + str(errors[0]),
                parent=root,
            )
            root.quit()
            return
        updater.launch_installed()
        handed_off.append(True)
        root.quit()

    root.after(40, finish)
    root.mainloop()
    if handed_off:
        os._exit(0)
    return False


def main() -> None:
    root = tk.Tk()
    if _handoff_to_install(root):
        return
    splash = SplashWindow(root, "launch")
    root.update()
    _close_bootloader_splash()

    errors: list[BaseException] = []

    def worker() -> None:
        try:
            _load_libraries()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=worker, name="ficklab-startup", daemon=True)
    thread.start()

    def finish_startup() -> None:
        if thread.is_alive():
            root.after(40, finish_startup)
            return
        splash.close()
        if errors:
            messagebox.showerror("FickLab could not start", str(errors[0]), parent=root)
            root.destroy()
            return
        import matplotlib

        matplotlib.use("TkAgg", force=True)
        import diffusion_app

        root.attributes("-topmost", False)
        root.resizable(True, True)
        diffusion_app.DiffusionApp(root)

    root.after(40, finish_startup)
    root.mainloop()


if __name__ == "__main__":
    main()
