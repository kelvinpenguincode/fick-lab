"""Desktop GUI for semi-infinite Fick diffusion, centered on the Scenario 3 grid search."""

from __future__ import annotations

import csv
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import matplotlib

matplotlib.rcParams["font.family"] = "Segoe UI"
matplotlib.rcParams["axes.unicode_minus"] = False

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

import app_version
import arrhenius
import scenario1
import scenario2
import scenario3
import splash_window
import updater


class DiffusionApp:
    """Interactive workbench for loading profiles and fitting D and C_s."""

    SCENARIOS = {
        "Scenario 1 — known Cₛ": "Cₛ is known. The fit estimates D only.",
        "Scenario 2 — Newton–Raphson (D, Cₛ)": "Time and bulk concentration are known. Newton–Raphson estimates D and Cₛ together.",
        "Scenario 3 — brute-force Cₛ grid": (
            "Tries surface concentrations from 0 up to the lowest measured value, fits D at each one, "
            "and keeps the pair with the smallest error. Use this when the surface is depleted, so Cₛ "
            "is at or below every measurement. C₀ should be the far-field plateau."
        ),
    }

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"FickLab {app_version.APP_VERSION}")
        self.dark_mode = False
        self.p = self._palette()
        self._theme_targets: list[tuple[tk.Widget, dict[str, str]]] = []
        self.root.configure(bg=self.p["canvas"])
        self._remember(self.root, bg="canvas")

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        initial_width = min(1280, max(960, int(screen_width * 0.82)))
        initial_height = min(820, max(620, int(screen_height * 0.82)))
        initial_width = min(initial_width, screen_width - 40)
        initial_height = min(initial_height, screen_height - 80)
        self.root.geometry(f"{initial_width}x{initial_height}")
        self.root.minsize(min(880, screen_width - 20), min(560, screen_height - 40))

        self.result_queue: queue.Queue = queue.Queue()
        self.notice_queue: queue.Queue = queue.Queue()
        self.update_busy = False
        self._update_splash = None
        self.fit_in_progress = False
        self._loading_visible = False
        self._loading_after = None
        self._loading_arm = None
        self._loading_mode = "fit"
        self._loading_fraction = None
        self._loading_started = 0.0
        self._loading_phase = 0.0
        self.loaded_data: tuple[np.ndarray, np.ndarray] | None = None
        self.loaded_headers: list[str] = []
        self.current_result = None
        self.current_fit_data = None
        self.profiles: dict[str, dict] = {}
        self.profile_order: list[str] = []
        self.tab_buttons: dict[str, tk.Button] = {}
        self.active_profile_id: str | None = None
        self._next_profile_number = 1
        self.figure: Figure | None = None
        self.canvas: FigureCanvasTkAgg | None = None
        self.toolbar: NavigationToolbar2Tk | None = None
        self._resize_job = None
        self._chart_resize_job = None
        self._poll_after_id = None
        self._draw_generation = 0

        self.scenario_var = tk.StringVar(value="Scenario 3 — brute-force Cₛ grid")
        self.file_var = tk.StringVar(value="")
        self.x_col_var = tk.StringVar(value="0")
        self.c_col_var = tk.StringVar(value="1")
        self.time_var = tk.StringVar(value="10")
        self.c0_var = tk.StringVar(value="100")
        self.cs_var = tk.StringVar(value="100")
        self.x_scale_var = tk.StringVar(value="1")
        self.x_unit_var = tk.StringVar(value="m")
        self.t_unit_var = tk.StringVar(value="h")
        self.c_unit_var = tk.StringVar(value="%")
        self.grid_steps_var = tk.StringVar(value="401")
        self.temperature_k_var = tk.StringVar(value="")
        self.temperature_c_var = tk.StringVar(value="")
        self.time_seconds_var = tk.StringVar(value="= 36000 s")
        self.graph_mode = tk.StringVar(value="profile")
        self.show_project = tk.BooleanVar(value=False)
        self.show_setup = tk.BooleanVar(value=True)
        self.show_workbook = tk.BooleanVar(value=False)
        self.show_metrics = tk.BooleanVar(value=False)
        self.show_advanced = tk.BooleanVar(value=False)
        self.export_width_in = tk.StringVar(value="10")
        self.export_height_in = tk.StringVar(value="6.5")
        self.export_dpi = tk.StringVar(value="300")
        self.status_var = tk.StringVar(value="Import a sheet, set time in hours, then Fit. Open extra tools from View.")
        self.hint_var = tk.StringVar(value="")
        self.summary_var = tk.StringVar(value="No workbook sheet loaded yet.")
        self.header_workspace_var = tk.StringVar(value="No sheets")
        self.chart_title_var = tk.StringVar(value="Graph 1  ·  concentration profile")
        self.chart_subtitle_var = tk.StringVar(value="Measured points appear here, then the fitted erfc curve.")
        self.formula_var = tk.StringVar(value="C(x, t) = C₀ + (Cₛ − C₀) · erfc( x / 2√(Dt) )")
        self.show_residuals = tk.BooleanVar(value=True)
        self.arrhenius_fit = None
        self._syncing_temperature = False
        self._refreshing_tree = False
        self.time_var.trace_add("write", lambda *_args: self._sync_time_seconds())
        self.temperature_k_var.trace_add("write", lambda *_args: self._on_temperature_k())
        self.temperature_c_var.trace_add("write", lambda *_args: self._on_temperature_c())

        self._configure_styles()
        self._build_menu()
        self._build_ui()
        self._apply_theme()
        self._create_profile("Sheet 1")
        self._update_scenario_controls()
        self.root.bind("<Configure>", self._schedule_responsive_layout, add="+")
        self.root.bind_all("<Return>", self._handle_enter_key)
        self.root.bind_all("<KP_Enter>", self._handle_enter_key)
        self.root.bind_all("<Control-o>", self._handle_open_shortcut)
        self.root.bind_all("<Control-Return>", self._handle_enter_key)
        self.root.bind_all("<Control-KP_Enter>", self._handle_enter_key)
        self.root.bind_all("<Control-Shift-s>", self._handle_save_plot_shortcut)
        self.root.bind_all("<F11>", self._toggle_fullscreen)
        self.root.bind("<Destroy>", self._on_root_destroy, add="+")
        self._poll_after_id = self.root.after(100, self._poll_result_queue)

    def _palette(self) -> dict[str, str]:
        if self.dark_mode:
            return {
                "canvas": "#202020",
                "card": "#2c2c2c",
                "ink": "#ffffff",
                "muted": "#c5c5c5",
                "line": "#3b3b3b",
                "accent": "#60cdff",
                "accent_active": "#4cc2ff",
                "on_accent": "#003543",
                "quiet": "#323232",
                "quiet_active": "#3d3d3d",
                "field": "#1e1e1e",
                "white": "#ffffff",
                "header": "#202020",
                "header_fg": "#ffffff",
                "header_muted": "#c5c5c5",
                "chip": "#323232",
                "chip_fg": "#ffffff",
                "point": "#99ebff",
                "curve": "#60cdff",
                "residual": "#ffb900",
                "formula_bg": "#1c1c1c",
                "formula_fg": "#99ebff",
                "grid": "#3b3b3b",
                "zero": "#e6e6e6",
                "tone_d": "#60cdff",
                "tone_cs": "#ffb900",
                "tone_r2": "#a6e9b8",
                "tone_rmse": "#ff99a4",
                "explorer": "#252525",
            }
        return {
            "canvas": "#f3f3f3",
            "card": "#ffffff",
            "ink": "#1a1a1a",
            "muted": "#5d5d5d",
            "line": "#e5e5e5",
            "accent": "#005fb8",
            "accent_active": "#003e92",
            "on_accent": "#ffffff",
            "quiet": "#f9f9f9",
            "quiet_active": "#eaeaea",
            "field": "#ffffff",
            "white": "#ffffff",
            "header": "#f9f9f9",
            "header_fg": "#1a1a1a",
            "header_muted": "#5d5d5d",
            "chip": "#f3f3f3",
            "chip_fg": "#1a1a1a",
            "point": "#005fb8",
            "curve": "#0f7b0f",
            "residual": "#c42b1c",
            "formula_bg": "#f0f6ff",
            "formula_fg": "#003e92",
            "grid": "#eeeeee",
            "zero": "#5d5d5d",
            "tone_d": "#005fb8",
            "tone_cs": "#9d5d00",
            "tone_r2": "#0f7b0f",
            "tone_rmse": "#c42b1c",
            "explorer": "#f9f9f9",
        }

    def _remember(self, widget: tk.Widget, **roles: str) -> tk.Widget:
        self._theme_targets.append((widget, roles))
        return widget

    def _frame(self, parent: tk.Widget, role: str = "card", **kwargs) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.p[role], **kwargs)
        return self._remember(frame, bg=role)

    def _lbl(
        self,
        parent: tk.Widget,
        text: str = "",
        *,
        bg: str,
        fg: str = "ink",
        size: int = 10,
        bold: bool = False,
        textvariable: tk.StringVar | None = None,
        **kwargs,
    ) -> tk.Label:
        label = tk.Label(
            parent,
            text=text,
            textvariable=textvariable,
            bg=self.p[bg],
            fg=self.p[fg],
            font=("Segoe UI", size, "bold" if bold else "normal"),
            anchor="w",
            justify="left",
            **kwargs,
        )
        return self._remember(label, bg=bg, fg=fg)

    def _button(self, parent: tk.Widget, text: str, command, kind: str = "quiet") -> ttk.Button:
        style_name = {"accent": "Accent.TButton", "tool": "Tool.TButton"}.get(kind, "Quiet.TButton")
        return ttk.Button(parent, text=text, command=command, style=style_name, cursor="hand2")

    def _on_root_destroy(self, event) -> None:
        if event.widget is not self.root:
            return
        for callback_id in (self._poll_after_id, self._resize_job, self._chart_resize_job, self._loading_after, self._loading_arm):
            if callback_id is not None:
                try:
                    self.root.after_cancel(callback_id)
                except tk.TclError:
                    pass

    def _configure_styles(self) -> None:
        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

    def _apply_ttk_styles(self) -> None:
        p = self.p
        self.style.configure(
            "TEntry",
            padding=7,
            fieldbackground=p["field"],
            foreground=p["ink"],
            bordercolor=p["line"],
            lightcolor=p["line"],
            darkcolor=p["line"],
        )
        self.style.map("TEntry", bordercolor=[("focus", p["accent"])], fieldbackground=[("disabled", p["quiet"])])
        self.style.configure(
            "TCombobox",
            padding=6,
            fieldbackground=p["field"],
            background=p["field"],
            foreground=p["ink"],
            arrowcolor=p["muted"],
            bordercolor=p["line"],
            lightcolor=p["line"],
            darkcolor=p["line"],
            arrowsize=12,
        )
        self.style.map("TCombobox", fieldbackground=[("readonly", p["field"]), ("disabled", p["quiet"])], foreground=[("disabled", p["muted"])])
        self.style.configure("TProgressbar", troughcolor=p["line"], background=p["accent"], thickness=4, borderwidth=0)
        self.style.configure("TPanedwindow", background=p["canvas"])
        self.style.configure(
            "Accent.TButton",
            padding=(12, 10),
            background=p["accent"],
            foreground=p["on_accent"],
            borderwidth=0,
            focusthickness=0,
            focuscolor=p["accent"],
            font=("Segoe UI", 10, "bold"),
            relief="flat",
        )
        self.style.map(
            "Accent.TButton",
            background=[("active", p["accent_active"]), ("disabled", p["line"])],
            foreground=[("disabled", p["muted"])],
        )
        self.style.configure(
            "Quiet.TButton",
            padding=(10, 7),
            background=p["quiet"],
            foreground=p["ink"],
            borderwidth=0,
            focusthickness=0,
            focuscolor=p["quiet"],
            font=("Segoe UI", 9),
            relief="flat",
        )
        self.style.map("Quiet.TButton", background=[("active", p["quiet_active"]), ("disabled", p["quiet"])], foreground=[("disabled", p["muted"])])
        self.style.configure(
            "Tool.TButton",
            padding=(10, 5),
            background=p["quiet"],
            foreground=p["ink"],
            borderwidth=0,
            focusthickness=0,
            focuscolor=p["quiet"],
            font=("Segoe UI", 9, "bold"),
            relief="flat",
        )
        self.style.map("Tool.TButton", background=[("active", p["quiet_active"])])
        self.style.configure(
            "Treeview",
            background=p["card"],
            fieldbackground=p["card"],
            foreground=p["ink"],
            bordercolor=p["line"],
            rowheight=24,
            font=("Segoe UI", 9),
        )
        self.style.configure("Treeview.Heading", background=p["quiet"], foreground=p["ink"], font=("Segoe UI", 8, "bold"), relief="flat")
        self.style.map("Treeview", background=[("selected", p["accent"])], foreground=[("selected", p["on_accent"])])

    def _apply_theme(self) -> None:
        self.p = self._palette()
        self._apply_ttk_styles()
        for widget, roles in self._theme_targets:
            try:
                if not widget.winfo_exists():
                    continue
                widget.configure(**{option: self.p[role] for option, role in roles.items()})
            except tk.TclError:
                pass
        menu_bg = self.p["card"]
        menu_fg = self.p["ink"]
        for menu in (self.app_menu, self.file_menu, self.view_menu, self.analysis_menu, self.help_menu):
            menu.configure(bg=menu_bg, fg=menu_fg, activebackground=self.p["accent"], activeforeground=self.p["on_accent"])
        self.theme_button.configure(
            text="Light mode" if self.dark_mode else "Dark mode",
            bg=self.p["chip"],
            fg=self.p["chip_fg"],
            activebackground=self.p["quiet_active"],
            activeforeground=self.p["chip_fg"],
        )
        self.update_button.configure(
            bg=self.p["chip"],
            fg=self.p["chip_fg"],
            activebackground=self.p["quiet_active"],
            activeforeground=self.p["chip_fg"],
        )
        self.workspace_chip.configure(bg=self.p["chip"], fg=self.p["chip_fg"])
        self.header.configure(bg=self.p["header"])
        self.header_mark.configure(bg=self.p["header"])
        self.header_titles.configure(bg=self.p["header"])
        self.header_title.configure(bg=self.p["header"], fg=self.p["header_fg"])
        self.header_subtitle.configure(bg=self.p["header"], fg=self.p["header_muted"])
        if hasattr(self, "ribbon"):
            self.ribbon.configure(bg=self.p["header"])
        self._style_pane_buttons()
        if hasattr(self, "residual_toggle"):
            self.residual_toggle.configure(
                bg=self.p["card"],
                fg=self.p["ink"],
                activebackground=self.p["card"],
                activeforeground=self.p["ink"],
                selectcolor=self.p["field"],
            )
        for stripe, tone in getattr(self, "metric_stripes", []):
            try:
                stripe.configure(bg=self.p[tone])
            except tk.TclError:
                pass
        for symbol, tone in getattr(self, "metric_symbols", []):
            try:
                symbol.configure(bg=self.p["card"], fg=self.p[tone])
            except tk.TclError:
                pass
        self._style_tabs()
        self._refresh_project_tree()
        self._refresh_workbook()
        if self.loaded_data is not None or self.current_result is not None or self.graph_mode.get() == "arrhenius":
            self._redraw_active_graph()
        else:
            self._show_placeholder()

    def _toggle_theme(self) -> None:
        self.dark_mode = not self.dark_mode
        self._apply_theme()

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Import workbook (CSV)…", accelerator="Ctrl+O", command=self._browse_csv)
        file_menu.add_command(label="Paste table", accelerator="Ctrl+V", command=self._paste_workbook)
        file_menu.add_command(label="Check for updates", command=self._check_for_updates)
        file_menu.add_separator()
        file_menu.add_command(label="Export fit report…", command=self._export_report)
        file_menu.add_command(label="Export graph…", accelerator="Ctrl+Shift+S", command=self._export_plot)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menu.add_cascade(label="File", menu=file_menu)
        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_command(label="Graph 1 · Profile", command=lambda: self._set_graph_mode("profile"))
        view_menu.add_command(label="Graph 2 · ln(D) vs 1/kT", command=lambda: self._set_graph_mode("arrhenius"))
        view_menu.add_separator()
        view_menu.add_checkbutton(label="Setup", variable=self.show_setup, command=self._sync_panes)
        view_menu.add_checkbutton(label="Project explorer", variable=self.show_project, command=self._sync_panes)
        view_menu.add_checkbutton(label="Workbook table", variable=self.show_workbook, command=self._sync_panes)
        view_menu.add_checkbutton(label="Result cards", variable=self.show_metrics, command=self._sync_panes)
        view_menu.add_checkbutton(label="Advanced options", variable=self.show_advanced, command=self._sync_panes)
        view_menu.add_separator()
        view_menu.add_command(label="Toggle dark appearance", command=self._toggle_theme)
        view_menu.add_command(label="Toggle fullscreen", accelerator="F11", command=self._toggle_fullscreen)
        menu.add_cascade(label="View", menu=view_menu)
        analysis_menu = tk.Menu(menu, tearoff=False)
        analysis_menu.add_command(label="Fit active sheet", accelerator="Enter", command=self._start_fit)
        analysis_menu.add_command(label="Linearize 1/kT plot", command=self._fit_arrhenius)
        menu.add_cascade(label="Analysis", menu=analysis_menu)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Tutorial", accelerator="F1", command=self._show_tutorial)
        help_menu.add_command(label="Keyboard shortcuts", command=self._show_shortcuts)
        help_menu.add_command(label="How updates work", command=self._show_update_guide)
        help_menu.add_command(label="Model assumptions", command=self._show_assumptions)
        help_menu.add_separator()
        help_menu.add_command(label="Check for updates", command=self._check_for_updates)
        help_menu.add_command(label="About FickLab", command=self._show_about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.root.configure(menu=menu)
        self.app_menu = menu
        self.file_menu = file_menu
        self.view_menu = view_menu
        self.analysis_menu = analysis_menu
        self.help_menu = help_menu
        self.root.bind_all("<F1>", lambda _event: self._show_tutorial())
        self.root.bind_all("<Control-v>", self._handle_paste_shortcut)

    def _handle_open_shortcut(self, _event=None):
        self._browse_csv()
        return "break"

    def _handle_save_plot_shortcut(self, _event=None):
        self._export_plot()
        return "break"

    def _toggle_fullscreen(self, _event=None):
        current = bool(self.root.attributes("-fullscreen"))
        self.root.attributes("-fullscreen", not current)
        return "break"

    def _show_shortcuts(self) -> None:
        messagebox.showinfo(
            "Keyboard shortcuts",
            "F1    Tutorial\n"
            "Ctrl+O    Import sheets\n"
            "Ctrl+V    Paste a table into the workbook\n"
            "Enter or Ctrl+Enter    Fit the active sheet\n"
            "Ctrl+Shift+S    Export the graph (choose size)\n"
            "F11    Toggle fullscreen\n\n"
            "View opens Setup, Project, Table, and Results when you need them.",
            parent=self.root,
        )

    def _tutorial_text(self) -> str:
        return (
            "FickLab 1.6.2 tutorial\n"
            "The graph is the main window. Open extra tools from View or the toolbar when you need them.\n"
            "Hover a measured point for depth, concentration, model, and residual. Click the point to copy those values.\n\n"
            "1. Import\n"
            "   File → Import, or Import on the toolbar, or Ctrl+O. Each CSV is a sheet.\n"
            "   Open Table to paste (Ctrl+V) or edit cells, then Apply table to plot.\n\n"
            "2. Time\n"
            "   Enter diffusion time in hours. The app converts to seconds automatically (1 h = 3600 s)\n"
            "   before fitting, so D is in (depth unit)²/s.\n\n"
            "3. Fit D\n"
            "   Set C₀, depth scale, and scenario, then Fit D or press Enter.\n"
            "   Graph 1 shows the measured profile, the erfc model, and residuals.\n\n"
            "4. Arrhenius 1/kT\n"
            "   Set temperature in K (or °C) on each fitted sheet. Open Graph 2 and Fit 1/kT line.\n"
            "   x = 1/(kT) with k = 8.617333262×10⁻⁵ eV/K. y = ln(D).\n"
            "   Error of ln(D) is σ_D / D (divide the diffusivity error by D itself).\n"
            "   Those y-errors weight the line. Slope and intercept errors come from that residual.\n"
            "   Relative errors are σ_slope/|slope| and σ_intercept/|intercept|.\n"
            "   ln(D) = ln(D₀) − E_a · (1/kT), so slope = −E_a (eV) and intercept = ln(D₀).\n\n"
            "5. Export a graph for a presentation\n"
            "   Export graph lets you set width, height (inches), and DPI, then save PNG, SVG, or PDF.\n\n"
            "6. Updates\n"
            "   Open FickLab from the Start menu shortcut. Check for updates replaces that copy.\n"
        )

    def _show_tutorial(self, _event=None):
        window = tk.Toplevel(self.root)
        window.title("FickLab tutorial")
        window.geometry("720x560")
        window.configure(bg=self.p["card"])
        window.transient(self.root)
        text = tk.Text(window, wrap="word", font=("Segoe UI", 10), bg=self.p["card"], fg=self.p["ink"], relief="flat", padx=16, pady=16)
        text.pack(fill="both", expand=True)
        text.insert("1.0", self._tutorial_text())
        text.configure(state="disabled")
        return "break"

    def _sync_time_seconds(self) -> None:
        try:
            hours = float(self.time_var.get().strip())
            seconds = arrhenius.hours_to_seconds(hours)
            self.time_seconds_var.set(f"= {seconds:g} s   (used in the Fick fit)")
        except (ValueError, TypeError):
            self.time_seconds_var.set("Enter hours. The fit uses seconds.")

    def _on_temperature_k(self) -> None:
        if self._syncing_temperature:
            return
        text = self.temperature_k_var.get().strip()
        if not text:
            return
        try:
            kelvin = float(text)
            self._syncing_temperature = True
            self.temperature_c_var.set(f"{arrhenius.kelvin_to_celsius(kelvin):.4g}")
        except ValueError:
            pass
        finally:
            self._syncing_temperature = False

    def _on_temperature_c(self) -> None:
        if self._syncing_temperature:
            return
        text = self.temperature_c_var.get().strip()
        if not text:
            return
        try:
            celsius = float(text)
            self._syncing_temperature = True
            self.temperature_k_var.set(f"{arrhenius.celsius_to_kelvin(celsius):.4g}")
        except ValueError:
            pass
        finally:
            self._syncing_temperature = False

    def _time_seconds(self) -> float:
        return arrhenius.hours_to_seconds(self._numeric_input(self.time_var, "Diffusion time in hours"))

    def _temperature_K(self) -> float | None:
        text = self.temperature_k_var.get().strip()
        if not text:
            return None
        kelvin = self._numeric_input(self.temperature_k_var, "Temperature")
        if kelvin <= 0:
            raise ValueError("Temperature must be positive kelvin")
        return kelvin

    def _set_graph_mode(self, mode: str) -> None:
        self.graph_mode.set(mode)
        if mode == "arrhenius":
            self._draw_arrhenius_chart()
        elif self.loaded_data is not None or self.current_result is not None:
            self._draw_chart()
        else:
            self._show_placeholder()

    def _redraw_active_graph(self) -> None:
        if self.graph_mode.get() == "arrhenius":
            self._draw_arrhenius_chart()
        elif self.loaded_data is not None or self.current_result is not None:
            self._draw_chart()
        else:
            self._show_placeholder()

    def _handle_paste_shortcut(self, _event=None):
        widget = self.root.focus_get()
        if isinstance(widget, (ttk.Entry, tk.Entry, tk.Text)):
            return None
        self._paste_workbook()
        return "break"

    def _show_assumptions(self) -> None:
        messagebox.showinfo(
            "Model assumptions",
            "FickLab uses the semi-infinite solid with a fixed surface concentration:\n\n"
            "C(x, t) = C₀ + (Cₛ − C₀) · erfc( x / (2 √(Dt)) )\n\n"
            "D is constant, the solid starts at a uniform concentration C₀, the surface stays at Cₛ, "
            "and the solid is thick compared with the diffusion length.\n\n"
            "Scenario 3 does not solve for Cₛ directly. It tries a grid of surface values from 0 "
            "through the lowest measured concentration, fits D for each one, and keeps the lowest error.",
            parent=self.root,
        )

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About FickLab",
            f"FickLab {app_version.APP_VERSION} is an Origin-style workbench for Fick profiles and Arrhenius 1/kT plots.\n\n"
            "Enter time in hours (converted to seconds), fit D, then linearize ln(D) vs 1/(kT).\n"
            "k = 8.617333262×10⁻⁵ eV/K. Error of ln(D) is σ_D / D.\n\n"
            "Check for updates replaces the Start menu copy when a higher GitHub release is published.",
            parent=self.root,
        )

    def _show_update_guide(self) -> None:
        messagebox.showinfo(
            "How updates work",
            "People who already have FickLab.exe use Check for updates.\n"
            "You publish a newer build with these steps:\n\n"
            "1. Create a GitHub repository and put owner/name on one line in github_repo.txt.\n"
            "2. Raise APP_VERSION in app_version.py. This copy is "
            f"{app_version.APP_VERSION}. The next release must be a higher number.\n"
            "3. Commit the change and push a tag such as v1.2.0.\n"
            "4. GitHub builds FickLab.exe and attaches it to that release.\n"
            "5. In the installed app, Check for updates downloads that file, replaces the Start menu copy, and restarts it.\n\n"
            "Open FickLab from the Start menu or the desktop shortcut. That is the copy updates replace. "
            "The version on the release has to be higher than the version inside that copy.",
            parent=self.root,
        )

    def _check_for_updates(self) -> None:
        if self.update_busy:
            self.status_var.set("An update check is already running.")
            return
        self.update_busy = True
        self.update_button.configure(state="disabled")
        self.status_var.set("Checking for updates…")
        self._show_update_splash("Checking for updates", "Looking up the latest GitHub release.")
        threading.Thread(target=self._update_check_worker, daemon=True).start()

    def _update_check_worker(self) -> None:
        try:
            info = updater.latest_release()
        except Exception as error:
            self.notice_queue.put(("update-error", str(error)))
            return
        self.notice_queue.put(("update-offer", info))

    def _drain_notices(self) -> None:
        try:
            while True:
                kind, payload = self.notice_queue.get_nowait()
                if kind == "update-status":
                    self.status_var.set(payload)
                elif kind == "update-progress":
                    self._loading_fraction = payload
                    percent = payload * 100
                    self.status_var.set(f"Downloading the update… {percent:.0f}%")
                    self._show_update_splash("Downloading the update", "The new FickLab replaces the Start menu copy and restarts.")
                    if self._update_splash is not None:
                        self._update_splash.set_progress(payload)
                elif kind == "update-error":
                    self._end_update_check()
                    self.status_var.set("Could not check for updates.")
                    messagebox.showerror("Updates", payload, parent=self.root)
                elif kind == "update-offer":
                    self._offer_update(payload)
                elif kind == "update-ready":
                    self._apply_downloaded_update(payload)
                elif kind == "update-download-error":
                    self._end_update_check()
                    self.status_var.set("The update did not download.")
                    messagebox.showerror("Updates", payload, parent=self.root)
        except queue.Empty:
            pass

    def _show_update_splash(self, title: str, detail: str) -> None:
        if self._update_splash is None:
            self._update_splash = splash_window.SplashWindow(tk.Toplevel(self.root), "update")
        self._update_splash.set_status(title, detail)

    def _close_update_splash(self) -> None:
        if self._update_splash is not None:
            self._update_splash.close()
            self._update_splash = None

    def _end_update_check(self) -> None:
        self.update_busy = False
        self._hide_loading()
        self._close_update_splash()
        if self.root.winfo_exists():
            self.update_button.configure(state="normal")

    def _offer_update(self, info: updater.ReleaseInfo) -> None:
        self._end_update_check()
        if not info.newer:
            self.status_var.set(f"FickLab {app_version.APP_VERSION} is the newest published build.")
            messagebox.showinfo(
                "Updates",
                f"You have version {app_version.APP_VERSION}.\n\n"
                f"The latest GitHub release is {info.version}, so there is nothing to install.",
                parent=self.root,
            )
            return
        notes = f"\n\n{info.notes}" if info.notes else ""
        if not getattr(sys, "frozen", False):
            open_page = messagebox.askyesno(
                "Update available",
                f"Version {info.version} is published. This window is running from Python source, "
                f"so it cannot replace itself.\n\nDownload FickLab.exe from the release page?{notes}",
                parent=self.root,
            )
            self.status_var.set(f"Version {info.version} is available.")
            if open_page:
                webbrowser.open(info.page_url)
            return
        install = messagebox.askyesno(
            "Update available",
            f"Version {info.version} is available. Download it and restart FickLab?{notes}",
            parent=self.root,
        )
        if not install:
            self.status_var.set(f"Version {info.version} is available.")
            return
        self.update_busy = True
        self.update_button.configure(state="disabled")
        self.status_var.set(f"Downloading version {info.version}…")
        self._loading_fraction = 0.0
        self._show_update_splash("Downloading the update", f"Version {info.version} will replace the installed FickLab and restart it.")
        if self._update_splash is not None:
            self._update_splash.set_progress(0.0)
        threading.Thread(target=self._download_update_worker, args=(info,), daemon=True).start()

    def _download_update_worker(self, info: updater.ReleaseInfo) -> None:
        def progress(fraction, total) -> None:
            if fraction is None:
                self.notice_queue.put(("update-status", f"Downloading version {info.version}… {total // 1024} KB"))
            else:
                self.notice_queue.put(("update-progress", fraction))

        try:
            path = updater.download_exe(info.download_url, progress)
        except Exception as error:
            self.notice_queue.put(("update-download-error", f"The download failed. {error}"))
            return
        self.notice_queue.put(("update-ready", (path, info.version)))

    def _apply_downloaded_update(self, payload) -> None:
        path, version = payload
        self.status_var.set("Restarting into the new version…")
        self._show_update_splash("Installing the update", "FickLab is closing. The new version opens from the Start menu shortcut.")
        if self._update_splash is not None:
            self._update_splash.set_progress(1.0)
        self.root.update()
        try:
            updater.schedule_replacement(path, version=version)
        except Exception as error:
            self._end_update_check()
            messagebox.showerror("Updates", str(error), parent=self.root)
            return
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        os._exit(0)

    def _build_ui(self) -> None:
        self.header = tk.Frame(self.root, bg=self.p["header"])
        self.header.pack(fill="x")
        self.header_mark = tk.Canvas(self.header, width=28, height=28, bg=self.p["header"], highlightthickness=0)
        self.header_mark.pack(side="left", padx=(14, 10), pady=8)
        self.header_mark.create_oval(2, 2, 26, 26, fill="#1e293b", outline="")
        self.header_mark.create_line(6, 18, 11, 14, 16, 16, 22, 8, fill="#2dd4bf", width=2, smooth=True, capstyle="round")
        self.header_mark.create_oval(20, 6, 24, 10, fill="#99f6e4", outline="")
        self.header_titles = tk.Frame(self.header, bg=self.p["header"])
        self.header_titles.pack(side="left", fill="y", pady=8)
        self.header_title = tk.Label(self.header_titles, text="FickLab", bg=self.p["header"], fg=self.p["header_fg"], font=("Segoe UI", 14, "bold"))
        self.header_title.pack(anchor="w")
        self.header_subtitle = tk.Label(
            self.header_titles,
            text="Open tools from View when you need them",
            bg=self.p["header"],
            fg=self.p["header_muted"],
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
        )
        self.header_subtitle.pack(anchor="w")
        self.theme_button = tk.Button(
            self.header,
            text="Dark mode",
            command=self._toggle_theme,
            bg=self.p["chip"],
            fg=self.p["chip_fg"],
            activebackground=self.p["quiet_active"],
            activeforeground=self.p["chip_fg"],
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self.theme_button.pack(side="right", padx=(0, 12), pady=8)
        self.update_button = tk.Button(
            self.header,
            text="Updates",
            command=self._check_for_updates,
            bg=self.p["chip"],
            fg=self.p["chip_fg"],
            activebackground=self.p["quiet_active"],
            activeforeground=self.p["chip_fg"],
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self.update_button.pack(side="right", padx=(0, 6), pady=8)
        self.workspace_chip = tk.Label(
            self.header,
            textvariable=self.header_workspace_var,
            bg=self.p["chip"],
            fg=self.p["chip_fg"],
            font=("Segoe UI", 9),
            padx=10,
            pady=4,
        )
        self.workspace_chip.pack(side="right", padx=(0, 6), pady=8)
        self.header.bind("<Configure>", self._fit_header_text, add="+")
        self.ribbon = tk.Frame(self.root, bg=self.p["header"])
        self.ribbon.pack(fill="x")
        actions = self._frame(self.ribbon, "header")
        actions.pack(side="left", padx=(8, 0), pady=4)
        for text, command in (
            ("Import", self._browse_csv),
            ("Fit", self._start_fit),
            ("1/kT", self._fit_arrhenius),
            ("Profile", lambda: self._set_graph_mode("profile")),
            ("Arrhenius", lambda: self._set_graph_mode("arrhenius")),
            ("Export", self._export_plot),
        ):
            self._button(actions, text, command, kind="tool").pack(side="left", padx=(0, 4))
        tools = self._frame(self.ribbon, "header")
        tools.pack(side="right", padx=(0, 8), pady=4)
        self._lbl(tools, "Tools", bg="header", fg="header_muted", size=8).pack(side="left", padx=(0, 6))
        self.pane_buttons: dict[str, ttk.Button] = {}
        for key, label, variable in (
            ("setup", "Setup", self.show_setup),
            ("project", "Project", self.show_project),
            ("workbook", "Table", self.show_workbook),
            ("metrics", "Results", self.show_metrics),
        ):
            button = self._button(tools, label, lambda name=key: self._toggle_named_pane(name), kind="tool")
            button.pack(side="left", padx=(0, 4))
            self.pane_buttons[key] = button
        self._frame(self.root, "accent", height=2).pack(fill="x")

        body = self._frame(self.root, "canvas")
        body.pack(fill="both", expand=True, padx=10, pady=(8, 6))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        page_bar = self._frame(body, "canvas")
        page_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        page_bar.grid_columnconfigure(0, weight=1)
        self.tab_row = self._frame(page_bar, "canvas")
        self.tab_row.grid(row=0, column=0, sticky="w")
        sheet_actions = self._frame(page_bar, "canvas")
        sheet_actions.grid(row=0, column=1, sticky="e")
        self.add_pages_button = self._button(sheet_actions, "+ Sheet", self._browse_csv, kind="tool")
        self.add_pages_button.pack(side="left", padx=(8, 6))
        self.close_page_button = self._button(sheet_actions, "Close", self._close_active_profile, kind="tool")
        self.close_page_button.pack(side="left")

        self.main_pane = tk.PanedWindow(
            body, orient="horizontal", sashwidth=8, sashrelief="flat", bd=0, bg=self.p["canvas"], opaqueresize=True
        )
        self._remember(self.main_pane, bg="canvas")
        self.main_pane.grid(row=1, column=0, sticky="nsew")

        explorer_outer = self._frame(self.main_pane, "explorer", highlightthickness=1, highlightbackground=self.p["line"])
        self.explorer_outer = self._remember(explorer_outer, bg="explorer", highlightbackground="line")
        self._lbl(explorer_outer, "PROJECT", bg="explorer", fg="muted", size=8, bold=True).pack(fill="x", padx=10, pady=(10, 4))
        self.explorer = ttk.Treeview(explorer_outer, show="tree", selectmode="browse")
        self.explorer.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        self.explorer.bind("<<TreeviewSelect>>", self._on_project_select)

        sidebar_outer = self._frame(self.main_pane, "card", highlightthickness=1, highlightbackground=self.p["line"])
        self.sidebar_outer = self._remember(sidebar_outer, bg="card", highlightbackground="line")
        self.sidebar_scroll_area = self._frame(sidebar_outer, "card")
        self.sidebar = self._make_scrollable_frame(self.sidebar_scroll_area)
        self._build_sidebar()
        self._build_sidebar_footer(sidebar_outer)
        self.sidebar_scroll_area.pack(side="top", fill="both", expand=True)

        self.content = self._frame(self.main_pane, "canvas")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)
        self._build_results_area()
        self._sync_panes()
        self.root.bind_all("<MouseWheel>", self._on_sidebar_mousewheel, add="+")
        self.root.bind_all("<Button-4>", self._on_sidebar_mousewheel, add="+")
        self.root.bind_all("<Button-5>", self._on_sidebar_mousewheel, add="+")

        status_bar = self._frame(self.root, "card", height=28, highlightthickness=1, highlightbackground=self.p["line"])
        self._remember(status_bar, highlightbackground="line")
        status_bar.pack(fill="x", side="bottom")
        status_bar.pack_propagate(False)
        self._lbl(status_bar, bg="card", fg="muted", size=9, textvariable=self.status_var).pack(side="left", padx=14, fill="y")

    def _make_scrollable_frame(self, parent: tk.Widget) -> tk.Frame:
        canvas = tk.Canvas(parent, bg=self.p["card"], highlightthickness=0, bd=0, height=120, highlightbackground=self.p["card"])
        self.sidebar_canvas = self._remember(canvas, bg="card")
        self.sidebar_scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=self._on_sidebar_scroll)
        self.sidebar_scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = self._frame(canvas, "card")
        self._sidebar_window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def resize_inner(event):
            canvas.itemconfigure(self._sidebar_window_id, width=event.width)
            wrap = max(220, event.width - 36)
            if hasattr(self, "scenario_hint_label"):
                self.scenario_hint_label.configure(wraplength=wrap)
            if hasattr(self, "summary_label"):
                self.summary_label.configure(wraplength=wrap)
            if hasattr(self, "footer_note"):
                self.footer_note.configure(wraplength=max(220, event.width - 8))
            self._refresh_sidebar_scroll()

        inner.bind("<Configure>", lambda _event: self._refresh_sidebar_scroll())
        canvas.bind("<Configure>", resize_inner)
        return inner

    def _on_sidebar_scroll(self, *values) -> None:
        self.sidebar_scrollbar.set(*values)
        self._update_sidebar_scrollbar()

    def _refresh_sidebar_scroll(self) -> None:
        canvas = getattr(self, "sidebar_canvas", None)
        inner = getattr(self, "sidebar", None)
        if canvas is None or inner is None:
            return
        try:
            inner.update_idletasks()
            height = max(inner.winfo_reqheight(), 1)
            width = max(canvas.winfo_width(), inner.winfo_reqwidth(), 1)
            canvas.configure(scrollregion=(0, 0, width, height))
            if height <= max(canvas.winfo_height(), 1):
                canvas.yview_moveto(0)
            self._update_sidebar_scrollbar()
        except tk.TclError:
            pass

    def _update_sidebar_scrollbar(self) -> None:
        canvas = getattr(self, "sidebar_canvas", None)
        bar = getattr(self, "sidebar_scrollbar", None)
        if canvas is None or bar is None:
            return
        try:
            first, last = canvas.yview()
            if last - first >= 0.999:
                bar.pack_forget()
            elif not bar.winfo_ismapped():
                bar.pack(side="right", fill="y")
        except tk.TclError:
            pass

    def _widget_under_pointer(self):
        try:
            return self.root.winfo_containing(self.root.winfo_pointerx(), self.root.winfo_pointery())
        except tk.TclError:
            return None

    def _inside_sidebar(self, widget) -> bool:
        sidebar = getattr(self, "sidebar_outer", None)
        while widget is not None:
            if widget is sidebar or widget is getattr(self, "sidebar_canvas", None):
                return True
            widget = getattr(widget, "master", None)
        return False

    def _fit_header_text(self, _event=None) -> None:
        if not hasattr(self, "header_subtitle"):
            return
        reserved = self.theme_button.winfo_width() + self.update_button.winfo_width() + self.workspace_chip.winfo_width() + 80
        self.header_subtitle.configure(wraplength=max(220, self.header.winfo_width() - reserved))

    def _on_sidebar_mousewheel(self, event):
        """Scroll the setup panel when the pointer is over it, even if focus is elsewhere."""
        hovered = self._widget_under_pointer()
        if not self._inside_sidebar(hovered) and not self._inside_sidebar(getattr(event, "widget", None)):
            return None
        if getattr(event, "num", None) == 4:
            units = -4
        elif getattr(event, "num", None) == 5:
            units = 4
        else:
            delta = getattr(event, "delta", 0)
            if not delta:
                return "break"
            notches = delta / 120.0 if abs(delta) >= 120 else float(delta)
            units = -int(round(notches * 4))
            if units == 0:
                units = -4 if delta > 0 else 4
        canvas = self.sidebar_canvas
        try:
            first, last = canvas.yview()
        except tk.TclError:
            return "break"
        if last - first >= 0.999:
            return "break"
        canvas.yview_scroll(units, "units")
        return "break"

    def _section(self, text: str) -> None:
        self._lbl(self.sidebar, text.upper(), bg="card", fg="muted", size=8, bold=True).pack(fill="x", padx=16, pady=(16, 6))

    def _field(self, title: str, variable: tk.StringVar) -> ttk.Entry:
        self._lbl(self.sidebar, title, bg="card", fg="muted", size=9).pack(fill="x", padx=16, pady=(8, 3))
        entry = ttk.Entry(self.sidebar, textvariable=variable)
        entry.pack(fill="x", padx=16)
        return entry

    def _build_sidebar(self) -> None:
        self._section("Fit")
        self.scenario_combo = ttk.Combobox(
            self.sidebar, textvariable=self.scenario_var, values=list(self.SCENARIOS), state="readonly"
        )
        self.scenario_combo.pack(fill="x", padx=16, pady=(0, 4))
        self.scenario_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_scenario_controls())
        self.time_entry = self._field("Time  t  (hours)", self.time_var)
        self.time_seconds_label = self._lbl(self.sidebar, bg="card", fg="muted", size=8, textvariable=self.time_seconds_var)
        self.time_seconds_label.pack(fill="x", padx=16, pady=(4, 0))
        self.c0_entry = self._field("Bulk C₀", self.c0_var)
        temp_row = self._frame(self.sidebar, "card")
        temp_row.pack(fill="x", padx=16, pady=(10, 0))
        temp_row.grid_columnconfigure(0, weight=1)
        temp_row.grid_columnconfigure(1, weight=1)
        self._lbl(temp_row, "T (K)", bg="card", fg="muted", size=9).grid(row=0, column=0, sticky="w", pady=(0, 3))
        self._lbl(temp_row, "T (°C)", bg="card", fg="muted", size=9).grid(row=0, column=1, sticky="w", padx=(8, 0), pady=(0, 3))
        ttk.Entry(temp_row, textvariable=self.temperature_k_var).grid(row=1, column=0, sticky="ew")
        ttk.Entry(temp_row, textvariable=self.temperature_c_var).grid(row=1, column=1, sticky="ew", padx=(8, 0))
        self._lbl(self.sidebar, "DATA", bg="card", fg="muted", size=8, bold=True).pack(fill="x", padx=16, pady=(12, 6))
        file_row = self._frame(self.sidebar, "card")
        file_row.pack(fill="x", padx=16)
        ttk.Entry(file_row, textvariable=self.file_var).pack(side="left", fill="x", expand=True)
        self._button(file_row, "Browse", self._browse_csv, kind="tool").pack(side="left", padx=(8, 0))
        self._button(self.sidebar, "Advanced options", lambda: self._toggle_named_pane("advanced"), kind="tool").pack(fill="x", padx=16, pady=(12, 8))

        self.advanced_frame = self._frame(self.root, "card")
        self.scenario_hint_label = self._lbl(self.advanced_frame, bg="card", fg="muted", size=9, textvariable=self.hint_var, wraplength=260)
        self.scenario_hint_label.pack(fill="x", padx=16, pady=(0, 8))
        columns = self._frame(self.advanced_frame, "card")
        columns.pack(fill="x", padx=16, pady=(8, 0))
        columns.grid_columnconfigure(0, weight=1)
        columns.grid_columnconfigure(1, weight=1)
        self._lbl(columns, "Depth column", bg="card", fg="muted", size=9).grid(row=0, column=0, sticky="w", pady=(0, 3))
        self._lbl(columns, "Concentration column", bg="card", fg="muted", size=9).grid(row=0, column=1, sticky="w", padx=(8, 0), pady=(0, 3))
        self.x_col_combo = ttk.Combobox(columns, textvariable=self.x_col_var, values=("0",))
        self.x_col_combo.grid(row=1, column=0, sticky="ew")
        self.c_col_combo = ttk.Combobox(columns, textvariable=self.c_col_var, values=("1",))
        self.c_col_combo.grid(row=1, column=1, sticky="ew", padx=(8, 0))
        self.x_col_combo.bind("<<ComboboxSelected>>", lambda _event: self._reload_active_file())
        self.c_col_combo.bind("<<ComboboxSelected>>", lambda _event: self._reload_active_file())
        self.summary_label = self._lbl(self.advanced_frame, bg="card", fg="ink", size=9, textvariable=self.summary_var, wraplength=260)
        self.summary_label.pack(fill="x", padx=16, pady=(10, 0))
        self._button(self.advanced_frame, "Use deepest points as C₀", self._suggest_c0, kind="tool").pack(fill="x", padx=16, pady=(8, 0))
        saved_sidebar = self.sidebar
        self.sidebar = self.advanced_frame
        self.cs_entry = self._field("Surface Cₛ  (Scenario 1)", self.cs_var)
        self.grid_entry = self._field("Cₛ grid points  (Scenario 3)", self.grid_steps_var)
        self.sidebar = saved_sidebar
        units = self._frame(self.advanced_frame, "card")
        units.pack(fill="x", padx=16, pady=(10, 4))
        for column in range(3):
            units.grid_columnconfigure(column, weight=1)
        captions = (("Depth scale", 0, 0), ("Depth unit", 1, 0), ("C unit", 2, 0))
        for caption, column, row in captions:
            self._lbl(units, caption, bg="card", fg="muted", size=9).grid(row=row, column=column, sticky="w", padx=(8 if column else 0, 0), pady=(0, 3))
        ttk.Entry(units, textvariable=self.x_scale_var).grid(row=1, column=0, sticky="ew")
        ttk.Entry(units, textvariable=self.x_unit_var).grid(row=1, column=1, sticky="ew", padx=(8, 0))
        ttk.Entry(units, textvariable=self.c_unit_var).grid(row=1, column=2, sticky="ew", padx=(8, 0))
        presets = self._frame(self.advanced_frame, "card")
        presets.pack(fill="x", padx=16, pady=(8, 4))
        preset_row = self._frame(presets, "card")
        preset_row.pack(fill="x")
        for label, scale, unit in (("As entered", "1", None), ("mm → m", "0.001", "m"), ("µm → m", "1e-6", "m")):
            self._button(preset_row, label, lambda s=scale, u=unit: self._apply_depth_preset(s, u), kind="tool").pack(side="left", padx=(0, 6))
        self.residual_toggle = tk.Checkbutton(
            self.advanced_frame,
            text="Show residual panel",
            variable=self.show_residuals,
            command=self._on_residual_toggle,
            bg=self.p["card"],
            fg=self.p["ink"],
            activebackground=self.p["card"],
            activeforeground=self.p["ink"],
            selectcolor=self.p["field"],
            font=("Segoe UI", 9),
            anchor="w",
            highlightthickness=0,
            bd=0,
        )
        self.residual_toggle.pack(fill="x", padx=16, pady=(8, 14))

    def _build_sidebar_footer(self, parent: tk.Widget) -> None:
        footer = self._frame(parent, "card", highlightthickness=1, highlightbackground=self.p["line"])
        self._remember(footer, highlightbackground="line")
        footer.pack(side="bottom", fill="x")
        self.fit_button = self._button(footer, "Fit diffusion profile", self._start_fit, kind="accent")
        self.fit_button.pack(fill="x", padx=14, pady=(12, 8))
        self.progress = ttk.Progressbar(footer, mode="indeterminate")
        self.progress.pack_forget()
        self.footer_note = self._lbl(
            footer,
            "Hover a point for values. Click to copy. View opens extra tools.",
            bg="card",
            fg="muted",
            size=8,
            wraplength=300,
        )
        self.footer_note.pack(fill="x", padx=14, pady=(0, 10))

    def _toggle_named_pane(self, name: str) -> None:
        mapping = {
            "setup": self.show_setup,
            "project": self.show_project,
            "workbook": self.show_workbook,
            "metrics": self.show_metrics,
            "advanced": self.show_advanced,
        }
        variable = mapping[name]
        variable.set(not variable.get())
        if name == "advanced" and variable.get():
            self.show_setup.set(True)
        self._sync_panes()

    def _sync_panes(self) -> None:
        if not hasattr(self, "main_pane"):
            return
        for child in list(self.main_pane.panes()):
            try:
                self.main_pane.forget(child)
            except tk.TclError:
                pass
        if self.show_project.get():
            self.main_pane.add(self.explorer_outer, minsize=160, width=200)
        if self.show_setup.get():
            self.main_pane.add(self.sidebar_outer, minsize=260, width=300)
        self.main_pane.add(self.content, minsize=520)
        if self.show_metrics.get():
            self.metric_cards_container.grid()
        else:
            self.metric_cards_container.grid_remove()
        if self.show_workbook.get():
            self.workspace.grid()
            self.content.grid_rowconfigure(1, weight=3)
            self.content.grid_rowconfigure(3, weight=1)
        else:
            self.workspace.grid_remove()
            self.content.grid_rowconfigure(1, weight=1)
            self.content.grid_rowconfigure(3, weight=0)
        if self.show_advanced.get():
            self.advanced_frame.pack(in_=self.sidebar, fill="x")
        else:
            self.advanced_frame.pack_forget()
        self._style_pane_buttons()
        self.root.after_idle(self._refresh_sidebar_scroll)
        self.root.after_idle(self._sync_figure_size)

    def _style_pane_buttons(self) -> None:
        labels = {
            "setup": "Setup",
            "project": "Project",
            "workbook": "Table",
            "metrics": "Results",
        }
        states = {
            "setup": self.show_setup.get(),
            "project": self.show_project.get(),
            "workbook": self.show_workbook.get(),
            "metrics": self.show_metrics.get(),
        }
        for key, button in getattr(self, "pane_buttons", {}).items():
            mark = "● " if states.get(key) else ""
            try:
                button.configure(text=f"{mark}{labels[key]}")
            except tk.TclError:
                pass

    def _build_results_area(self) -> None:
        self.metric_cards_container = self._frame(self.content, "canvas")
        self.metric_cards_container.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        for column in range(4):
            self.metric_cards_container.grid_columnconfigure(column, weight=1, uniform="metrics")
        self.metric_vars = {key: tk.StringVar(value="—") for key in ("D", "Cs", "r2", "rmse")}
        self.metric_units = {key: tk.StringVar(value="") for key in self.metric_vars}
        self.metric_details = {
            "D": tk.StringVar(value="Fitted from the profile"),
            "Cs": tk.StringVar(value="Fitted from the profile"),
            "r2": tk.StringVar(value="1.0000 is an exact match"),
            "rmse": tk.StringVar(value="Average miss of the curve"),
        }
        cards = (
            ("D", "Diffusivity", "D", "tone_d"),
            ("Cs", "Surface concentration", "Cₛ", "tone_cs"),
            ("r2", "Fit quality", "R²", "tone_r2"),
            ("rmse", "Typical error", "RMSE", "tone_rmse"),
        )
        self.metric_cards = []
        self.metric_stripes = []
        self.metric_symbols = []
        for index, (key, name, symbol, tone) in enumerate(cards):
            card = self._frame(self.metric_cards_container, "card", highlightthickness=1, highlightbackground=self.p["line"])
            self._remember(card, highlightbackground="line")
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 8, 0))
            self.metric_cards.append(card)
            stripe = tk.Frame(card, bg=self.p[tone], width=5)
            stripe.pack(side="left", fill="y")
            stripe.pack_propagate(False)
            self.metric_stripes.append((stripe, tone))
            body = self._frame(card, "card")
            body.pack(side="left", fill="both", expand=True, padx=(12, 10), pady=(7, 7))
            title_row = self._frame(body, "card")
            title_row.pack(fill="x")
            self._lbl(title_row, name, bg="card", fg="muted", size=9).pack(side="left")
            symbol_label = tk.Label(title_row, text=symbol, bg=self.p["card"], fg=self.p[tone], font=("Segoe UI", 9, "bold"))
            symbol_label.pack(side="left", padx=(6, 0))
            self.metric_symbols.append((symbol_label, tone))
            value_row = self._frame(body, "card")
            value_row.pack(fill="x", pady=(1, 0))
            self._lbl(value_row, bg="card", fg="ink", size=20, bold=True, textvariable=self.metric_vars[key]).pack(side="left")
            self._lbl(value_row, bg="card", fg="ink", size=10, textvariable=self.metric_units[key]).pack(side="left", padx=(8, 0), pady=(10, 0))
            self._lbl(body, bg="card", fg="muted", size=8, textvariable=self.metric_details[key], wraplength=240).pack(anchor="w", pady=(1, 0))

        chart_card = self._frame(self.content, "card", highlightthickness=1, highlightbackground=self.p["line"])
        self._remember(chart_card, highlightbackground="line")
        chart_card.grid(row=1, column=0, sticky="nsew")
        chart_card.grid_columnconfigure(0, weight=1)
        chart_card.grid_rowconfigure(1, weight=1)
        chart_header = self._frame(chart_card, "card")
        chart_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(8, 0))
        heading = self._frame(chart_header, "card")
        heading.pack(side="left", fill="both", expand=True)
        self._lbl(heading, bg="card", fg="ink", size=13, bold=True, textvariable=self.chart_title_var).pack(anchor="w")
        self.chart_subtitle_label = self._lbl(heading, bg="card", fg="muted", size=9, textvariable=self.chart_subtitle_var, wraplength=420)
        self.chart_subtitle_label.pack(anchor="w", fill="x", pady=(2, 0))
        heading.bind("<Configure>", lambda event: self.chart_subtitle_label.configure(wraplength=max(180, event.width - 8)), add="+")
        button_row = self._frame(chart_header, "card")
        button_row.pack(side="right", anchor="n")
        self.copy_button = self._button(button_row, "Copy", self._copy_results, kind="tool")
        self.copy_button.pack(side="left", padx=(0, 6))
        self.report_button = self._button(button_row, "Export CSV", self._export_report, kind="tool")
        self.report_button.pack(side="left", padx=(0, 6))
        self.image_button = self._button(button_row, "Save image", self._export_plot, kind="tool")
        self.image_button.pack(side="left")
        self._set_export_enabled(False)

        self.chart_host = self._frame(chart_card, "card")
        self.chart_host.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 2))
        self.chart_host.pack_propagate(False)
        self.chart_host.bind("<Configure>", self._schedule_chart_resize)
        self.loading_canvas = tk.Canvas(self.chart_host, highlightthickness=0, bd=0, bg=self.p["card"])
        self._show_placeholder()

        formula = self._frame(self.content, "formula_bg")
        formula.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self._lbl(
            formula,
            bg="formula_bg",
            fg="formula_fg",
            size=9,
            textvariable=self.formula_var,
        ).pack(side="left", padx=12, pady=4)

        workspace = self._frame(self.content, "canvas")
        workspace.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        workspace.grid_columnconfigure(0, weight=1)
        workspace.grid_rowconfigure(1, weight=1)
        self.content.grid_rowconfigure(1, weight=1)
        self.content.grid_rowconfigure(3, weight=0)
        self.workspace = workspace
        book = self._frame(workspace, "card", highlightthickness=1, highlightbackground=self.p["line"])
        self._remember(book, highlightbackground="line")
        book.grid(row=1, column=0, sticky="nsew")
        book.grid_columnconfigure(0, weight=1)
        book.grid_rowconfigure(1, weight=1)
        book_header = self._frame(book, "card")
        book_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 0))
        self._lbl(book_header, "Workbook", bg="card", fg="ink", size=11, bold=True).pack(side="left")
        self._lbl(book_header, "Double-click a cell to edit. Ctrl+V pastes a table.", bg="card", fg="muted", size=8).pack(side="left", padx=(10, 0))
        self._button(book_header, "Apply table to plot", self._apply_workbook, kind="tool").pack(side="right")
        columns = ("row", "depth", "concentration", "model", "residual")
        self.workbook = ttk.Treeview(book, columns=columns, show="headings", selectmode="browse", height=7)
        headings = (("row", "#"), ("depth", "Depth"), ("concentration", "C"), ("model", "Model"), ("residual", "Residual"))
        for key, title in headings:
            self.workbook.heading(key, text=title)
            self.workbook.column(key, width=80 if key != "row" else 40, anchor="e")
        self.workbook.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))
        self.workbook.bind("<Double-1>", self._edit_workbook_cell)

    def _show_placeholder(self) -> None:
        self._draw_generation += 1
        self.figure = None
        self.canvas = None
        self.toolbar = None
        self._clear_chart_widgets()
        holder = tk.Frame(self.chart_host, bg=self.p["card"])
        holder.pack(expand=True, fill="both")
        tk.Label(
            holder,
            text="The concentration profile will be plotted here.\n\nImport a workbook sheet or paste a table, then fit Cₛ and D.",
            bg=self.p["card"],
            fg=self.p["muted"],
            font=("Segoe UI", 12),
            justify="center",
        ).pack(expand=True)
        self._raise_loading()

    def _clear_chart_widgets(self) -> None:
        for child in list(self.chart_host.winfo_children()):
            if child is getattr(self, "loading_canvas", None):
                continue
            child.destroy()

    def _raise_loading(self) -> None:
        if self._loading_visible and self.loading_canvas.winfo_exists():
            self.loading_canvas.tk.call("raise", self.loading_canvas._w)

    def _arm_loading(self, mode: str, delay_ms: int = 160) -> None:
        self._cancel_loading_timer(self._loading_arm)
        self._loading_arm = None
        self._loading_mode = mode
        if mode != "download":
            self._loading_fraction = None
        self._loading_started = time.monotonic()
        if delay_ms <= 0:
            self._show_loading()
        else:
            self._loading_arm = self.root.after(delay_ms, self._show_loading)

    def _show_loading(self) -> None:
        self._loading_arm = None
        if not self.root.winfo_exists():
            return
        self._loading_visible = True
        self.loading_canvas.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._raise_loading()
        self._tick_loading()

    def _hide_loading(self) -> None:
        self._cancel_loading_timer(self._loading_arm)
        self._cancel_loading_timer(self._loading_after)
        self._loading_arm = None
        self._loading_after = None
        self._loading_visible = False
        self._loading_fraction = None
        if hasattr(self, "loading_canvas") and self.loading_canvas.winfo_exists():
            self.loading_canvas.place_forget()

    def _cancel_loading_timer(self, callback_id) -> None:
        if callback_id is None:
            return
        try:
            self.root.after_cancel(callback_id)
        except tk.TclError:
            pass

    def _loading_copy(self, elapsed: float) -> tuple[str, str]:
        if self._loading_mode == "download":
            percent = ""
            if self._loading_fraction is not None:
                percent = f"   {self._loading_fraction * 100:.0f}%"
            return f"Downloading the update{percent}", "FickLab replaces itself and restarts when the file is ready."
        if self._loading_mode == "update":
            return "Checking for updates", "Looking up the latest GitHub release."
        if elapsed < 2:
            return "Fitting the profile", "Comparing the measurements with the erfc model."
        if elapsed < 6:
            return "Still working", "Trying surface concentrations and keeping the closest match."
        return "This one is taking a while", "The window stays open. The chart updates when the best D and Cₛ are found."

    def _tick_loading(self) -> None:
        if not self._loading_visible or not self.root.winfo_exists():
            return
        canvas = self.loading_canvas
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width < 20 or height < 20:
            self._loading_after = self.root.after(32, self._tick_loading)
            return
        canvas.delete("all")
        palette = self.p
        canvas.configure(bg=palette["card"])
        self._loading_phase += 0.05
        phase = self._loading_phase
        for index in range(1, 5):
            line_y = 36 + (height - 88) * index / 5
            canvas.create_line(64, line_y, width - 64, line_y, fill=palette["grid"])
        spread = 0.16 + 0.2 * (0.5 + 0.5 * math.sin(phase * 0.65))
        steps = 90
        left, right = 72.0, max(73.0, width - 72.0)
        base = height * 0.68
        amplitude = max(48.0, height * 0.26)
        coordinates: list[float] = []
        for index in range(steps):
            fraction = index / (steps - 1)
            height_fraction = math.erfc(fraction / (2.0 * spread))
            coordinates.extend((left + fraction * (right - left), base - height_fraction * amplitude))
        canvas.create_line(*coordinates, fill=palette["curve"], width=3, smooth=True, capstyle="round")
        bead = int((0.15 + 0.7 * (0.5 + 0.5 * math.sin(phase))) * (steps - 1))
        bead_x = coordinates[bead * 2]
        bead_y = coordinates[bead * 2 + 1]
        glow = 11 + 3 * math.sin(phase * 2.2)
        canvas.create_oval(bead_x - glow, bead_y - glow, bead_x + glow, bead_y + glow, outline=palette["curve"], width=2)
        canvas.create_oval(bead_x - 4.5, bead_y - 4.5, bead_x + 4.5, bead_y + 4.5, fill=palette["accent"], outline="")
        elapsed = max(0.0, time.monotonic() - self._loading_started)
        title, detail = self._loading_copy(elapsed)
        canvas.create_text(width / 2, 42, text=title, fill=palette["ink"], font=("Segoe UI", 18, "bold"))
        canvas.create_text(
            width / 2,
            72,
            text=detail,
            fill=palette["muted"],
            font=("Segoe UI", 11),
            width=max(220, width - 140),
        )
        canvas.create_text(
            width / 2,
            104,
            text=f"{int(elapsed // 60)}:{int(elapsed % 60):02d}",
            fill=palette["accent"],
            font=("Segoe UI", 13, "bold"),
        )
        track_y = height - 28
        track_left = 72.0
        track_right = max(track_left + 8, width - 72.0)
        canvas.create_line(track_left, track_y, track_right, track_y, fill=palette["line"], width=5, capstyle="round")
        if self._loading_fraction is None:
            span = (track_right - track_left) * 0.28
            travel = max(0.0, track_right - track_left - span)
            start = track_left + (0.5 + 0.5 * math.sin(phase * 1.35)) * travel
            canvas.create_line(start, track_y, start + span, track_y, fill=palette["accent"], width=5, capstyle="round")
        else:
            filled = track_left + (track_right - track_left) * max(0.0, min(1.0, self._loading_fraction))
            canvas.create_line(track_left, track_y, filled, track_y, fill=palette["accent"], width=5, capstyle="round")
        self._loading_after = self.root.after(32, self._tick_loading)

    def _schedule_responsive_layout(self, event=None) -> None:
        if event is not None and event.widget is not self.root:
            return
        if self._resize_job is not None:
            try:
                self.root.after_cancel(self._resize_job)
            except tk.TclError:
                pass
        self._resize_job = self.root.after(80, self._apply_responsive_layout)

    def _apply_responsive_layout(self) -> None:
        self._resize_job = None
        width = self.content.winfo_width()
        if width <= 1 or not hasattr(self, "metric_cards"):
            return
        columns = 4 if width >= 860 else 2 if width >= 520 else 1
        for index, card in enumerate(self.metric_cards):
            row, column = divmod(index, columns)
            card.grid_configure(row=row, column=column, padx=(0 if column == 0 else 8, 0), pady=(0 if row == 0 else 8, 0), sticky="nsew")
        for column in range(4):
            self.metric_cards_container.grid_columnconfigure(
                column,
                weight=1 if column < columns else 0,
                uniform="metrics" if column < columns else "",
            )

    def _schedule_chart_resize(self, event=None) -> None:
        if event is not None and event.widget is not self.chart_host:
            return
        if self.figure is None:
            return
        if self._chart_resize_job is not None:
            try:
                self.root.after_cancel(self._chart_resize_job)
            except tk.TclError:
                pass
        self._chart_resize_job = self.root.after(60, self._sync_figure_size)

    def _sync_figure_size(self) -> None:
        self._chart_resize_job = None
        if self.figure is None or self.canvas is None or self.toolbar is None:
            return
        width = self.chart_host.winfo_width()
        height = self.chart_host.winfo_height() - max(self.toolbar.winfo_height(), 32)
        if width < 120 or height < 120:
            return
        dpi = float(self.figure.dpi)
        target = (width / dpi, height / dpi)
        current = self.figure.get_size_inches()
        if abs(current[0] - target[0]) < 0.05 and abs(current[1] - target[1]) < 0.05:
            return
        self.figure.set_size_inches(*target, forward=True)
        widget = self.canvas.get_tk_widget()
        widget.configure(width=width, height=max(height, 1))
        self.canvas.draw_idle()

    def _style_tabs(self) -> None:
        for profile_id, button in self.tab_buttons.items():
            selected = profile_id == self.active_profile_id
            button.configure(
                bg=self.p["card"] if selected else self.p["canvas"],
                fg=self.p["accent"] if selected else self.p["muted"],
                activebackground=self.p["card"],
                activeforeground=self.p["ink"],
                font=("Segoe UI", 9, "bold" if selected else "normal"),
            )

    def _short_label(self, text: str, limit: int = 28) -> str:
        text = text.strip() or "Profile"
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def _set_tab_text(self, profile_id: str, text: str) -> None:
        button = self.tab_buttons.get(profile_id)
        if button is not None:
            button.configure(text=self._short_label(text))

    def _create_profile(self, label: str, *, select: bool = True) -> str:
        profile_id = f"profile-{self._next_profile_number}"
        self._next_profile_number += 1
        self.profiles[profile_id] = {
            "path": "",
            "data": None,
            "headers": [],
            "x_col": "0",
            "c_col": "1",
            "result": None,
            "fit_data": None,
            "label": label,
            "time_hours": self.time_var.get(),
            "temperature_k": self.temperature_k_var.get(),
        }
        self.profile_order.append(profile_id)
        button = tk.Button(
            self.tab_row,
            text=self._short_label(label),
            command=lambda profile_id=profile_id: self._select_profile(profile_id),
            relief="flat",
            bd=0,
            padx=12,
            pady=7,
            cursor="hand2",
            bg=self.p["canvas"],
            fg=self.p["muted"],
            activebackground=self.p["card"],
            font=("Segoe UI", 9),
        )
        button.pack(side="left", padx=(0, 4))
        self.tab_buttons[profile_id] = button
        if select or self.active_profile_id is None:
            self._select_profile(profile_id)
        else:
            self._style_tabs()
        self._update_header_workspace()
        return profile_id

    def _update_header_workspace(self) -> None:
        total = len(self.profiles)
        fitted = sum(profile["result"] is not None for profile in self.profiles.values())
        if total == 0:
            self.header_workspace_var.set("No profiles")
        elif fitted:
            self.header_workspace_var.set(f"{total} profile{'s' if total != 1 else ''}  ·  {fitted} fitted")
        else:
            self.header_workspace_var.set(f"{total} profile{'s' if total != 1 else ''}")

    def _close_active_profile(self) -> None:
        if self.active_profile_id is None:
            return
        if self.fit_in_progress:
            self.status_var.set("Wait for the current fit to finish before closing a page.")
            return
        profile_id = self.active_profile_id
        if len(self.profiles) == 1:
            self.profiles[profile_id] = {
                "path": "",
                "data": None,
                "headers": [],
                "x_col": "0",
                "c_col": "1",
                "result": None,
                "fit_data": None,
                "label": "Sheet 1",
                "time_hours": self.time_var.get(),
                "temperature_k": self.temperature_k_var.get(),
            }
            self._set_tab_text(profile_id, "Sheet 1")
            self._restore_profile(profile_id)
            return
        index = self.profile_order.index(profile_id)
        self.profile_order.remove(profile_id)
        self.profiles.pop(profile_id, None)
        button = self.tab_buttons.pop(profile_id, None)
        if button is not None:
            button.destroy()
        self.active_profile_id = None
        neighbor = self.profile_order[min(index, len(self.profile_order) - 1)]
        self._select_profile(neighbor)

    def _save_active_profile(self) -> None:
        if self.active_profile_id is None or self.active_profile_id not in self.profiles:
            return
        self.profiles[self.active_profile_id].update(
            path=self.file_var.get(),
            data=self.loaded_data,
            headers=self.loaded_headers,
            x_col=self.x_col_var.get(),
            c_col=self.c_col_var.get(),
            result=self.current_result,
            fit_data=self.current_fit_data,
            time_hours=self.time_var.get(),
            temperature_k=self.temperature_k_var.get(),
        )
        self._update_header_workspace()

    def _restore_profile(self, profile_id: str) -> None:
        self.active_profile_id = profile_id
        profile = self.profiles[profile_id]
        self.file_var.set(profile["path"])
        self.loaded_data = profile["data"]
        self.loaded_headers = profile["headers"]
        self.x_col_var.set(profile["x_col"])
        self.c_col_var.set(profile["c_col"])
        columns = profile["headers"] or ["0", "1"]
        self.x_col_combo.configure(values=columns)
        self.c_col_combo.configure(values=columns)
        self.current_result = profile["result"]
        self.current_fit_data = profile["fit_data"]
        if profile.get("time_hours"):
            self.time_var.set(profile["time_hours"])
        if "temperature_k" in profile:
            self.temperature_k_var.set(profile.get("temperature_k") or "")
        self._refresh_summary()
        self._style_tabs()
        self._refresh_project_tree()
        self._refresh_workbook()
        if self.current_result is None:
            self._clear_metrics()
            self._set_export_enabled(False)
            if self.loaded_data is None:
                self.chart_title_var.set("Concentration profile")
                self.chart_subtitle_var.set("Measured points appear here, then the fitted erfc curve.")
                self._show_placeholder()
                self.status_var.set("Profile ready. Add a CSV, then fit.")
            else:
                self._draw_chart()
                self.status_var.set("Profile loaded. Set time and C₀, then fit.")
        else:
            self._show_chart_result()
            source = profile["path"] or "this profile"
            self.status_var.set(f"Showing the saved fit for {Path(source).name if source else 'this profile'}.")
        self._update_header_workspace()

    def _select_profile(self, profile_id: str) -> None:
        if profile_id not in self.profiles:
            return
        if profile_id == self.active_profile_id:
            self._style_tabs()
            return
        self._save_active_profile()
        self._restore_profile(profile_id)

    def _handle_enter_key(self, _event=None):
        if str(self.fit_button.cget("state")) == "disabled":
            return "break"
        self._start_fit()
        return "break"

    def _update_scenario_controls(self) -> None:
        scenario = self.scenario_var.get()
        self.hint_var.set(self.SCENARIOS.get(scenario, ""))
        self.cs_entry.configure(state="normal" if scenario.startswith("Scenario 1") else "disabled")
        self.grid_entry.configure(state="normal" if scenario.startswith("Scenario 3") else "disabled")

    def _clear_metrics(self) -> None:
        for variable in self.metric_vars.values():
            variable.set("—")
        for variable in self.metric_units.values():
            variable.set("")
        waiting = {
            "D": "Fitted from the profile",
            "Cs": "Fitted from the profile",
            "r2": "1.0000 is an exact match",
            "rmse": "Average miss of the curve",
        }
        for key, text in waiting.items():
            self.metric_details[key].set(text)
        self.formula_var.set("C(x, t) = C₀ + (Cₛ − C₀) · erfc( x / 2√(Dt) )")

    def _pretty_number(self, value: float, kind: str) -> str:
        if not math.isfinite(value):
            return "—"
        if kind == "r2":
            return f"{value:.4f}"
        magnitude = abs(value)
        if magnitude == 0:
            return "0"
        if magnitude < 0.01 or magnitude >= 10000:
            exponent = int(math.floor(math.log10(magnitude)))
            mantissa = value / 10**exponent
            digits = f"{mantissa:.3f}".rstrip("0").rstrip(".")
            if digits in {"", "-", "-0"}:
                digits = "0"
            return f"{digits}×10{self._superscript(exponent)}"
        if kind == "rmse":
            return f"{value:.4g}"
        return f"{value:.5g}"

    @staticmethod
    def _superscript(number: int) -> str:
        return str(number).translate(str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹"))

    def _diffusion_length(self, diffusivity: float, time: float) -> float:
        return 2.0 * math.sqrt(diffusivity * time)

    def _suggest_c0(self) -> None:
        if self.loaded_data is None:
            self.status_var.set("Load a profile before estimating C₀.")
            return
        depths, concentrations = self.loaded_data
        order = np.argsort(np.asarray(depths, dtype=float))
        count = max(3, concentrations.size // 10)
        estimate = float(np.median(np.asarray(concentrations, dtype=float)[order[-count:]]))
        self.c0_var.set(f"{estimate:.6g}")
        self.status_var.set(f"C₀ set to {estimate:.6g} from the deepest measurements.")

    def _apply_depth_preset(self, scale: str, unit: str | None) -> None:
        self.x_scale_var.set(scale)
        if unit:
            self.x_unit_var.set(unit)
        self._refresh_summary()
        if self.current_result is None and self.loaded_data is not None:
            self._draw_chart()
        self.status_var.set(f"Depth scale set to {scale}" + (f", unit {unit}." if unit else "."))

    def _on_residual_toggle(self) -> None:
        if self.loaded_data is not None or self.current_result is not None:
            self._draw_chart()

    def _set_export_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in (self.copy_button, self.report_button, self.image_button):
            button.configure(state=state)

    def _depth_scale(self) -> float:
        try:
            scale = float(self.x_scale_var.get().strip())
        except ValueError:
            return 1.0
        return scale if math.isfinite(scale) and scale > 0 else 1.0

    def _refresh_summary(self) -> None:
        if self.loaded_data is None:
            self.summary_var.set("No measurements loaded on this page.")
            return
        depths, concentrations = self.loaded_data
        scaled = np.asarray(depths, dtype=float) * self._depth_scale()
        concentrations = np.asarray(concentrations, dtype=float)
        depth_unit = self.x_unit_var.get().strip() or "depth"
        concentration_unit = self.c_unit_var.get().strip()
        unit_suffix = f" {concentration_unit}" if concentration_unit else ""
        lines = [
            f"{concentrations.size} points",
            f"Depth  {float(np.min(scaled)):.4g} – {float(np.max(scaled)):.4g} {depth_unit}",
            f"Concentration  {float(np.min(concentrations)):.4g} – {float(np.max(concentrations)):.4g}{unit_suffix}",
        ]
        if concentrations.size > 2 and float(np.ptp(scaled)) > 0 and float(np.ptp(concentrations)) > 0:
            correlation = float(np.corrcoef(scaled, concentrations)[0, 1])
            if correlation > 0.3:
                lines.append("Concentration rises with depth, so the surface is the low end of the profile.")
            elif correlation < -0.3:
                lines.append("Concentration falls with depth. Scenario 3 only searches Cₛ below the lowest point; Scenario 2 can fit a higher surface.")
        self.summary_var.set("\n".join(lines))

    def _detect_csv_header(self, file_path: str) -> list[str]:
        with open(file_path, newline="", encoding="utf-8-sig") as csv_file:
            sample = csv_file.read(8192)
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
        first_line = sample.splitlines()[0] if sample.splitlines() else ""
        first_row = next(csv.reader([first_line], delimiter=delimiter), [])
        if not first_row:
            return []
        try:
            float(first_row[0])
            return [str(index) for index in range(len(first_row))]
        except ValueError:
            return [value.strip().lstrip("\ufeff") for value in first_row]

    def _profile_is_empty(self, profile_id: str | None) -> bool:
        if profile_id is None or profile_id not in self.profiles:
            return True
        profile = self.profiles[profile_id]
        return not profile["path"] and profile["data"] is None

    def _browse_csv(self) -> None:
        if self.fit_in_progress:
            self.status_var.set("Wait for the current fit to finish before adding pages.")
            return
        file_paths = filedialog.askopenfilenames(
            title="Select one or more concentration-depth files",
            filetypes=[("CSV and text data", "*.csv *.tsv *.txt *.dat"), ("All files", "*.*")],
        )
        if not file_paths:
            return
        self._import_paths(file_paths)

    def _import_paths(self, file_paths) -> None:
        if self.fit_in_progress:
            self.status_var.set("Wait for the current fit to finish before adding pages.")
            return
        self._save_active_profile()
        last_id = self.active_profile_id
        added = 0
        for index, file_path in enumerate(file_paths):
            replace_current = index == 0 and self._profile_is_empty(self.active_profile_id)
            profile_id = self.active_profile_id if replace_current else self._create_profile(Path(file_path).name, select=False)
            try:
                headers = self._detect_csv_header(file_path)
                x_col = headers[0] if headers else "0"
                c_col = headers[1] if len(headers) > 1 else "1"
                depths, concentrations = scenario1.load_csv(file_path, x_col, c_col)
                self.profiles[profile_id].update(
                    path=file_path,
                    data=(depths, concentrations),
                    headers=headers,
                    x_col=x_col,
                    c_col=c_col,
                    result=None,
                    fit_data=None,
                    label=Path(file_path).name,
                )
                self._set_tab_text(profile_id, Path(file_path).name)
                last_id = profile_id
                added += 1
            except (OSError, UnicodeError, csv.Error, ValueError) as error:
                if profile_id == self.active_profile_id and replace_current:
                    messagebox.showerror("Could not read file", str(error), parent=self.root)
                elif profile_id != self.active_profile_id:
                    self.profile_order.remove(profile_id)
                    self.profiles.pop(profile_id, None)
                    button = self.tab_buttons.pop(profile_id, None)
                    if button is not None:
                        button.destroy()
                    messagebox.showerror("Could not read file", f"{Path(file_path).name}\n\n{error}", parent=self.root)
        if last_id is not None:
            self.active_profile_id = None
            self._select_profile(last_id)
            self._refresh_project_tree()
        self.status_var.set(f"Added {added} sheet{'s' if added != 1 else ''}. Set hours and C₀, then fit.")

    def _reload_active_file(self) -> None:
        path = self.file_var.get().strip()
        if not path or not Path(path).is_file():
            return
        if self.fit_in_progress:
            return
        try:
            depths, concentrations = scenario1.load_csv(path, self.x_col_var.get().strip() or "0", self.c_col_var.get().strip() or "1")
        except (OSError, UnicodeError, csv.Error, ValueError) as error:
            self.status_var.set(str(error))
            return
        self.loaded_data = (depths, concentrations)
        self.loaded_headers = self._detect_csv_header(path)
        self.current_result = None
        self.current_fit_data = None
        self._clear_metrics()
        self._set_export_enabled(False)
        self._save_active_profile()
        self._refresh_summary()
        self._refresh_workbook()
        self._draw_chart()
        self.status_var.set("Columns updated. Fit again to refresh D and Cₛ.")

    def _numeric_input(self, variable: tk.StringVar, label: str) -> float:
        try:
            value = float(variable.get().strip())
        except ValueError as error:
            raise ValueError(f"{label} must be a number") from error
        if not math.isfinite(value):
            raise ValueError(f"{label} must be finite")
        return value

    def _start_fit(self) -> None:
        if self.fit_in_progress:
            return
        if self.loaded_data is None and not Path(self.file_var.get().strip()).is_file():
            messagebox.showinfo("Choose data", "Select a CSV file of depth and concentration first.", parent=self.root)
            return
        try:
            hours = self._numeric_input(self.time_var, "Diffusion time in hours")
            time = arrhenius.hours_to_seconds(hours)
            temperature = self._temperature_K()
            c0 = self._numeric_input(self.c0_var, "C₀")
            x_scale = self._numeric_input(self.x_scale_var, "Depth scale")
            if x_scale <= 0:
                raise ValueError("Depth scale must be positive")
            scenario = self.scenario_var.get()
            cs = self._numeric_input(self.cs_var, "Cₛ") if scenario.startswith("Scenario 1") else None
            steps = int(self._numeric_input(self.grid_steps_var, "Cₛ grid points")) if scenario.startswith("Scenario 3") else None
            if steps is not None and steps < 2:
                raise ValueError("Scenario 3 needs at least two Cₛ grid points")
        except ValueError as error:
            messagebox.showerror("Check the inputs", str(error), parent=self.root)
            return

        source_path = self.file_var.get().strip()
        if Path(source_path).is_file():
            data_snapshot = None
        elif self.loaded_data is not None:
            data_snapshot = (self.loaded_data[0].copy(), self.loaded_data[1].copy())
            source_path = ""
        else:
            messagebox.showinfo("Choose data", "Select a CSV file of depth and concentration first.", parent=self.root)
            return

        options = {
            "scenario": scenario,
            "time": time,
            "time_hours": hours,
            "temperature_K": temperature,
            "c0": c0,
            "cs": cs,
            "steps": steps,
            "x_scale": x_scale,
            "source_path": source_path,
            "data": data_snapshot,
            "x_col": self.x_col_var.get().strip() or "0",
            "c_col": self.c_col_var.get().strip() or "1",
            "profile_id": self.active_profile_id,
            "x_unit": self.x_unit_var.get().strip() or "depth",
            "c_unit": self.c_unit_var.get().strip(),
            "t_unit": "s",
            "source_label": self.profiles.get(self.active_profile_id, {}).get("label", "Profile"),
        }
        self.fit_button.configure(state="disabled", text="Fitting…")
        self.fit_in_progress = True
        self.add_pages_button.configure(state="disabled")
        self.close_page_button.configure(state="disabled")
        self._arm_loading("fit")
        if scenario.startswith("Scenario 3"):
            self.status_var.set("Searching the Cₛ grid and fitting D for each candidate…")
        else:
            self.status_var.set("Fitting the diffusion profile…")
        threading.Thread(target=self._fit_worker, args=(options,), daemon=True).start()

    def _fit_worker(self, options: dict) -> None:
        try:
            if options["data"] is not None:
                raw_x, raw_c = options["data"]
            else:
                raw_x, raw_c = scenario1.load_csv(options["source_path"], options["x_col"], options["c_col"])
            raw_x = np.asarray(raw_x, dtype=float)
            raw_c = np.asarray(raw_c, dtype=float)
            x = raw_x * options["x_scale"]
            if options["scenario"].startswith("Scenario 1"):
                result = scenario1.fit_diffusion_coefficient(x, raw_c, options["time"], options["cs"], options["c0"])
                surface = options["cs"]
            elif options["scenario"].startswith("Scenario 2"):
                result = scenario2.fit_parameters(x, raw_c, options["time"], options["c0"])
                surface = result.C_s
            else:
                result = scenario3.fit_by_brute_force(x, raw_c, options["time"], options["c0"], options["steps"])
                surface = result.C_s
            self.result_queue.put(("success", options, x, raw_c, result, surface, raw_x))
        except Exception as error:
            self.result_queue.put(("error", str(error)))

    def _finish_fit_controls(self) -> None:
        self._hide_loading()
        self.fit_button.configure(state="normal", text="Fit diffusion profile")
        self.fit_in_progress = False
        self.add_pages_button.configure(state="normal")
        self.close_page_button.configure(state="normal")

    def _poll_result_queue(self) -> None:
        if not self.root.winfo_exists():
            return
        self._drain_notices()
        try:
            while True:
                message = self.result_queue.get_nowait()
                self._finish_fit_controls()
                if message[0] == "error":
                    self.status_var.set("The fit did not complete.")
                    messagebox.showerror("Fit failed", message[1], parent=self.root)
                    continue
                _, options, x, measured_c, result, surface, raw_x = message
                self._display_result(options, x, measured_c, result, surface, raw_x)
        except queue.Empty:
            pass
        except tk.TclError:
            return
        if self.root.winfo_exists():
            self._poll_after_id = self.root.after(100, self._poll_result_queue)

    def _display_result(self, options: dict, x: np.ndarray, measured_c: np.ndarray, result, surface: float, raw_x: np.ndarray) -> None:
        profile_id = options.get("profile_id")
        if profile_id not in self.profiles:
            self.status_var.set("The fit finished, but that profile page is closed.")
            return
        source = options["source_label"] if not options["source_path"] else Path(options["source_path"]).name
        fit_data = {
            "x": x,
            "measured_c": measured_c,
            "t": options["time"],
            "t_hours": options["time_hours"],
            "temperature_K": options["temperature_K"],
            "C_s": surface,
            "C_0": options["c0"],
            "x_unit": options["x_unit"],
            "c_unit": options["c_unit"],
            "t_unit": options["t_unit"],
            "scenario": options["scenario"],
            "source": source,
            "x_column": options["x_col"],
            "c_column": options["c_col"],
            "x_scale": options["x_scale"],
            "cs_steps": options["steps"],
        }
        self.profiles[profile_id].update(
            path=options["source_path"] or self.profiles[profile_id]["path"],
            data=(raw_x, measured_c),
            x_col=options["x_col"],
            c_col=options["c_col"],
            result=result,
            fit_data=fit_data,
        )
        self._update_header_workspace()
        if profile_id != self.active_profile_id:
            self.status_var.set(f"Fit complete for {source}. Select that page to view it.")
            return
        self.loaded_data = (raw_x, measured_c)
        self.current_result = result
        self.current_fit_data = fit_data
        self._show_chart_result()
        note = ""
        if getattr(result, "at_lower_bound", False):
            note = " Cₛ is on the lower edge of the search."
        self.status_var.set(f"Fit complete  ·  {source}  ·  {len(x)} points  ·  {options['scenario']}.{note}")

    def _show_chart_result(self) -> None:
        result = self.current_result
        fit = self.current_fit_data
        if result is None or fit is None:
            return
        concentration_unit = fit["c_unit"].strip() if fit["c_unit"] else "concentration"
        d_unit = f"{fit['x_unit']}² / {fit['t_unit']}"
        length = self._diffusion_length(result.D, fit["t"])
        self.metric_vars["D"].set(self._pretty_number(result.D, "D"))
        self.metric_units["D"].set(d_unit)
        d_notes = [f"L = {length:.4g} {fit['x_unit']}"]
        if result.D_err and math.isfinite(result.D_err):
            d_notes.insert(0, f"± {self._pretty_number(result.D_err, 'D')}")
        self.metric_details["D"].set("   ·   ".join(d_notes))
        self.metric_vars["Cs"].set(self._pretty_number(fit["C_s"], "Cs"))
        self.metric_units["Cs"].set(concentration_unit)
        cs_notes = []
        if getattr(result, "C_s_err", None) and math.isfinite(result.C_s_err):
            cs_notes.append(f"± {self._pretty_number(result.C_s_err, 'Cs')}")
        if getattr(result, "C_s_grid_step", None):
            cs_notes.append(f"grid step {self._pretty_number(result.C_s_grid_step, 'Cs')}")
        if getattr(result, "at_lower_bound", False):
            cs_notes.append("at the lower edge")
        self.metric_details["Cs"].set("   ·   ".join(cs_notes) if cs_notes else "Best surface value")
        self.metric_vars["r2"].set(f"{result.r_squared:.4f}")
        self.metric_units["r2"].set("")
        self.metric_details["r2"].set("1.0000 is an exact match")
        self.metric_vars["rmse"].set(self._pretty_number(result.rmse, "rmse"))
        self.metric_units["rmse"].set(concentration_unit)
        self.metric_details["rmse"].set("Root-mean-square residual")
        length = self._diffusion_length(result.D, fit["t"])
        self.formula_var.set(f"C(x, t) = C₀ + (Cₛ − C₀) · erfc( x / 2√(Dt) )      L = {length:.4g} {fit['x_unit']}")
        self.chart_title_var.set("Graph 1  ·  measured profile and fitted model")
        hours = fit.get("t_hours")
        time_note = f"t = {hours:g} h = {fit['t']:g} s" if hours else f"t = {fit['t']:g} {fit['t_unit']}"
        temperature = fit.get("temperature_K")
        if temperature:
            time_note += f"   ·   T = {temperature:g} K   ·   1/kT = {arrhenius.inv_kT(temperature):.4g} eV⁻¹"
        self.chart_subtitle_var.set(f"{fit['scenario']}   ·   {fit['source']}   ·   {len(fit['x'])} points   ·   {time_note}")
        self._set_export_enabled(True)
        self._refresh_summary()
        self._refresh_workbook()
        self._refresh_project_tree()
        if self.graph_mode.get() == "arrhenius":
            self._draw_arrhenius_chart()
        else:
            self._draw_chart()

    def _draw_chart(self) -> None:
        raw = self.loaded_data
        fit = self.current_fit_data
        result = self.current_result
        if raw is None and fit is None:
            self._show_placeholder()
            return
        self._draw_generation += 1
        generation = self._draw_generation
        self._disconnect_plot_events()
        self._clear_chart_widgets()
        self.figure = None
        self.canvas = None
        self.toolbar = None

        width = max(self.chart_host.winfo_width(), 640)
        height = max(self.chart_host.winfo_height() - 36, 360)
        if self.chart_host.winfo_width() < 80:
            self.root.after(80, lambda token=generation: self._draw_chart() if token == self._draw_generation else None)
            width, height = 900, 520
        dpi = 110
        p = self.p
        self.figure = Figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor=p["card"])
        has_fit = result is not None and fit is not None
        show_residuals = has_fit and bool(self.show_residuals.get())
        if has_fit:
            x = np.asarray(fit["x"], dtype=float)
            measured = np.asarray(fit["measured_c"], dtype=float)
            depth_unit = fit["x_unit"]
            concentration_unit = fit["c_unit"]
        else:
            x = np.asarray(raw[0], dtype=float) * self._depth_scale()
            measured = np.asarray(raw[1], dtype=float)
            depth_unit = self.x_unit_var.get().strip() or "depth"
            concentration_unit = self.c_unit_var.get().strip()
        if show_residuals:
            gridspec = self.figure.add_gridspec(2, 1, height_ratios=(4.6, 1.0), left=0.08, right=0.985, bottom=0.09, top=0.97, hspace=0.14)
            ax = self.figure.add_subplot(gridspec[0])
            residual_ax = self.figure.add_subplot(gridspec[1], sharex=ax)
        else:
            ax = self.figure.add_subplot(111)
            residual_ax = None
            self.figure.subplots_adjust(left=0.08, right=0.985, bottom=0.1, top=0.96)
            if not has_fit:
                self.chart_title_var.set("Graph 1  ·  concentration profile")
                self.chart_subtitle_var.set(f"{measured.size} points   ·   fit to overlay the model")

        concentration_label = f"Concentration ({concentration_unit})" if concentration_unit else "Concentration"
        for artist_ax in (ax, residual_ax):
            if artist_ax is None:
                continue
            artist_ax.set_facecolor(p["card"])
            artist_ax.grid(True, color=p["grid"], linewidth=0.7)
            artist_ax.tick_params(colors=p["muted"], labelsize=8, length=0)
            for spine_name, spine in artist_ax.spines.items():
                spine.set_color(p["line"])
                if spine_name in ("top", "right"):
                    spine.set_visible(False)

        order = np.argsort(x)
        ax.scatter(
            x, measured, s=18 if measured.size > 180 else 32, color=p["point"],
            edgecolors=p["card"], linewidths=0.6, alpha=0.9, label="Measured", zorder=4,
        )
        predicted = None
        if has_fit:
            curve_x = np.linspace(float(np.min(x)), float(np.max(x)) * 1.01 if np.max(x) > 0 else 1.0, 500)
            if float(np.min(curve_x)) > 0:
                curve_x = np.linspace(0.0, float(np.max(x)) * 1.01, 500)
            curve_y = scenario1.concentration(curve_x, result.D, fit["t"], fit["C_s"], fit["C_0"])
            predicted = scenario1.concentration(x, result.D, fit["t"], fit["C_s"], fit["C_0"])
            ax.fill_between(curve_x, fit["C_0"], curve_y, color=p["curve"], alpha=0.08, zorder=1)
            ax.plot(curve_x, curve_y, color=p["curve"], linewidth=2.4, label="Fitted erfc", zorder=3)
            ax.axhline(fit["C_0"], color=p["muted"], linewidth=1.0, linestyle=(0, (4, 3)), label=f"C₀ = {fit['C_0']:g}")
            if residual_ax is not None:
                residual = measured - predicted
                residual_ax.axhspan(-result.rmse, result.rmse, color=p["residual"], alpha=0.12)
                residual_ax.axhline(0.0, color=p["zero"], linewidth=1.0)
                residual_ax.scatter(x, residual, s=12, color=p["residual"], alpha=0.85, zorder=3)
                residual_ax.set_ylabel("Residual", color=p["ink"], fontsize=9)
                residual_ax.set_xlabel(f"Depth ({depth_unit})", color=p["ink"], fontsize=9)
                residual_ax.tick_params(axis="x", labelbottom=True)
                ax.tick_params(axis="x", labelbottom=False)
            else:
                ax.set_xlabel(f"Depth ({depth_unit})", color=p["ink"], fontsize=9)
            self._place_fit_note(ax, x, measured, result, fit)
        else:
            ax.set_xlabel(f"Depth ({depth_unit})", color=p["ink"], fontsize=9)
        ax.set_ylabel(concentration_label, color=p["ink"], fontsize=9)
        legend = ax.legend(frameon=False, loc="best", fontsize=8)
        for text in legend.get_texts():
            text.set_color(p["ink"])

        self.canvas = FigureCanvasTkAgg(self.figure, master=self.chart_host)
        self.canvas.draw()
        widget = self.canvas.get_tk_widget()
        widget.configure(bg=p["card"])
        self.toolbar = NavigationToolbar2Tk(self.canvas, self.chart_host, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side="bottom", fill="x")
        widget.pack(side="top", fill="both", expand=True)
        try:
            self.toolbar.configure(background=p["card"])
            for child in self.toolbar.winfo_children():
                child.configure(background=p["card"])
        except tk.TclError:
            pass
        depth_name = depth_unit
        c_name = concentration_unit or "C"
        predicted_values = predicted

        def format_profile_point(index: int) -> str:
            lines = [
                f"Depth  {x[index]:.5g} {depth_name}",
                f"Measured  {measured[index]:.5g} {c_name}".rstrip(),
            ]
            if predicted_values is not None:
                residual = measured[index] - predicted_values[index]
                lines.append(f"Model  {predicted_values[index]:.5g} {c_name}".rstrip())
                lines.append(f"Residual  {residual:+.4g}")
            return "\n".join(lines)

        self._attach_plot_hover(ax, x, measured, format_profile_point)
        self.root.after_idle(self._sync_figure_size)
        self._raise_loading()

    def _place_fit_note(self, ax, x, measured, result, fit) -> None:
        x_span = float(np.ptp(x)) or 1.0
        y_span = float(np.ptp(measured)) or 1.0
        norm_x = (x - float(np.min(x))) / x_span
        norm_y = (measured - float(np.min(measured))) / y_span
        corners = {
            "upper left": (0.03, 0.97, "left", "top", norm_x <= 0.35, norm_y >= 0.65),
            "upper right": (0.97, 0.97, "right", "top", norm_x >= 0.65, norm_y >= 0.65),
            "lower left": (0.03, 0.04, "left", "bottom", norm_x <= 0.35, norm_y <= 0.35),
            "lower right": (0.97, 0.04, "right", "bottom", norm_x >= 0.65, norm_y <= 0.35),
        }
        name = min(corners, key=lambda key: np.count_nonzero(corners[key][4] & corners[key][5]))
        text_x, text_y, ha, va, *_ = corners[name]
        note = "\n".join(
            (
                f"D     {self._pretty_number(result.D, 'D')}",
                f"Cₛ    {self._pretty_number(fit['C_s'], 'Cs')}",
                f"R²    {result.r_squared:.4f}",
            )
        )
        ax.text(
            text_x,
            text_y,
            note,
            transform=ax.transAxes,
            ha=ha,
            va=va,
            fontsize=11,
            fontname="Segoe UI",
            color=self.p["ink"],
            linespacing=1.45,
            bbox={"boxstyle": "round,pad=0.55", "facecolor": self.p["card"], "edgecolor": self.p["accent"], "linewidth": 1.2, "alpha": 0.96},
            zorder=6,
        )

    def _disconnect_plot_events(self) -> None:
        if self.canvas is None:
            return
        for attr in ("_motion_cid", "_click_cid"):
            cid = getattr(self, attr, None)
            if cid is None:
                continue
            try:
                self.canvas.mpl_disconnect(cid)
            except Exception:
                pass
            setattr(self, attr, None)

    def _attach_plot_hover(self, ax, x, y, formatter) -> None:
        self.hover_annotation = ax.annotate(
            "",
            xy=(0, 0),
            xytext=(12, 12),
            textcoords="offset points",
            bbox={"boxstyle": "round,pad=0.4", "fc": "#1c1c1c", "ec": "#6b6b6b", "linewidth": 0.6, "alpha": 0.96},
            color="#f4f0ea",
            fontsize=8,
            visible=False,
            zorder=10,
        )
        self._plot_hover_data = (ax, np.asarray(x, dtype=float), np.asarray(y, dtype=float), formatter)
        self._motion_cid = self.canvas.mpl_connect("motion_notify_event", self._on_plot_motion)
        self._click_cid = self.canvas.mpl_connect("button_press_event", self._on_plot_click)
        try:
            self.canvas.get_tk_widget().configure(cursor="crosshair")
        except tk.TclError:
            pass

    def _hover_index(self, event):
        if not hasattr(self, "hover_annotation") or self.canvas is None or not hasattr(self, "_plot_hover_data"):
            return None
        ax, x, y, _formatter = self._plot_hover_data
        if event.inaxes is not ax or event.xdata is None or event.ydata is None or x.size == 0:
            return None
        pixels = ax.transData.transform(np.column_stack((x, y)))
        distance = np.hypot(pixels[:, 0] - event.x, pixels[:, 1] - event.y)
        nearest = int(np.argmin(distance))
        if distance[nearest] > 22:
            return None
        return nearest

    def _on_plot_motion(self, event) -> None:
        if not hasattr(self, "hover_annotation") or self.canvas is None or not hasattr(self, "_plot_hover_data"):
            return
        ax, x, y, formatter = self._plot_hover_data
        nearest = self._hover_index(event)
        if nearest is None:
            if event.inaxes is ax and event.xdata is not None and event.ydata is not None:
                self.status_var.set(f"x = {event.xdata:.5g}    y = {event.ydata:.5g}")
            if self.hover_annotation.get_visible():
                self.hover_annotation.set_visible(False)
                self.canvas.draw_idle()
            return
        text = formatter(nearest)
        self.hover_annotation.xy = (x[nearest], y[nearest])
        self.hover_annotation.set_text(text)
        self.hover_annotation.set_visible(True)
        self.status_var.set(text.replace("\n", "   ·   "))
        self.canvas.draw_idle()

    def _on_plot_click(self, event) -> None:
        if event.button != 1:
            return
        nearest = self._hover_index(event)
        if nearest is None or not hasattr(self, "_plot_hover_data"):
            return
        _ax, _x, _y, formatter = self._plot_hover_data
        text = formatter(nearest)
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status_var.set("Copied point values")
        except tk.TclError:
            pass

    def _summary_text(self) -> str:
        if self.current_result is None or self.current_fit_data is None:
            return "No fit result yet."
        fit = self.current_fit_data
        result = self.current_result
        d_unit = f"{fit['x_unit']}^2 / {fit['t_unit']}"
        cs_unit = fit["c_unit"] or "concentration unit"
        lines = [
            f"Scenario: {fit['scenario']}",
            f"Source: {fit['source']}",
            f"Points: {len(fit['x'])}",
            f"Time: {fit.get('t_hours', fit['t']/3600):g} h = {fit['t']:g} s",
            f"Temperature: {fit.get('temperature_K') or '—'} K",
            f"C_0: {fit['C_0']:g} {cs_unit}",
            f"D: {result.D:.8g} {d_unit}",
            f"Diffusion length L: {self._diffusion_length(result.D, fit['t']):.6g} {fit['x_unit']}",
            f"D standard error: {result.D_err:.5g} {d_unit}",
            f"C_s: {fit['C_s']:.8g} {cs_unit}",
            f"R^2: {result.r_squared:.8g}",
            f"RMSE: {result.rmse:.8g} {cs_unit}",
        ]
        if getattr(result, "C_s_grid_step", None):
            lines.append(f"C_s grid step: {result.C_s_grid_step:.6g} {cs_unit}")
            lines.append(f"C_s search: 0 to {getattr(result, 'search_high', float('nan')):.6g} {cs_unit}")
        if getattr(result, "at_lower_bound", False):
            lines.append("Note: C_s is on the lower edge of the search interval.")
        return "\n".join(lines) + "\n"

    def _copy_results(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self._summary_text())
        self.status_var.set("Fit summary copied.")

    def _default_export_stem(self) -> str:
        fit = self.current_fit_data
        if fit is None:
            return "ficklab_fit"
        source_stem = Path(str(fit["source"])).stem
        scenario_tag = fit["scenario"].split("—", maxsplit=1)[0].strip().lower().replace(" ", "_")
        if not source_stem or source_stem.lower() in {"profile", "profile 1"}:
            source_stem = "ficklab"
        return f"{source_stem}_{scenario_tag}_fit"

    def _export_report(self) -> None:
        if self.current_result is None or self.current_fit_data is None:
            return
        path = filedialog.asksaveasfilename(
            title="Export fit summary",
            defaultextension=".csv",
            initialfile=f"{self._default_export_stem()}_results.csv",
            filetypes=[("CSV file", "*.csv")],
        )
        if not path:
            return
        result = self.current_result
        fit = self.current_fit_data
        predicted_c = scenario1.concentration(fit["x"], result.D, fit["t"], fit["C_s"], fit["C_0"])
        time_unit = fit["t_unit"]
        d_unit = f"{fit['x_unit']}^2 / {time_unit}"
        cs_unit = fit["c_unit"] or "concentration unit"
        with open(path, "w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            writer.writerow(("FickLab fit report", "value", "unit"))
            writer.writerow(("Scenario / method", fit["scenario"], ""))
            writer.writerow(("Source file", fit["source"], ""))
            writer.writerow(("Number of fitted points", len(fit["x"]), "points"))
            writer.writerow(("Depth column", fit["x_column"], ""))
            writer.writerow(("Concentration column", fit["c_column"], ""))
            writer.writerow(("Depth scale applied", fit["x_scale"], "multiplier"))
            writer.writerow(("Diffusion time t", fit.get("t_hours", ""), "h"))
            writer.writerow(("Diffusion time t", fit["t"], time_unit))
            writer.writerow(("Temperature", fit.get("temperature_K") or "", "K"))
            if fit.get("temperature_K"):
                writer.writerow(("1/kT", arrhenius.inv_kT(fit["temperature_K"]), "eV^-1"))
            if result.D > 0 and result.D_err:
                ln_D, ln_err = arrhenius.ln_diffusion_error(result.D, result.D_err)
                writer.writerow(("ln(D)", ln_D, ""))
                writer.writerow(("error of ln(D) = sigma_D / D", ln_err, ""))
            writer.writerow(("Initial / bulk concentration C_0", fit["C_0"], cs_unit))
            writer.writerow(("Diffusion coefficient D", result.D, d_unit))
            writer.writerow(("D standard error", result.D_err, d_unit))
            writer.writerow(("Surface concentration C_s", fit["C_s"], cs_unit))
            if hasattr(result, "C_s_err"):
                writer.writerow(("C_s standard error", result.C_s_err, cs_unit))
            if fit["cs_steps"] is not None:
                writer.writerow(("C_s grid candidates", fit["cs_steps"], "points"))
                writer.writerow(("C_s grid spacing", result.C_s_grid_step, cs_unit))
                high = getattr(result, "search_high", float(np.min(fit["measured_c"])))
                writer.writerow(("C_s search interval", f"0 to {high:g}", cs_unit))
            writer.writerow(("Coefficient of determination R_squared", result.r_squared, ""))
            writer.writerow(("Root mean squared error RMSE", result.rmse, cs_unit))
            writer.writerow(())
            writer.writerow(("Measured profile and fitted values",))
            writer.writerow((f"Depth ({fit['x_unit']})", f"Measured concentration ({cs_unit})", f"Model concentration ({cs_unit})", f"Residual ({cs_unit})"))
            for depth, measured, predicted in zip(fit["x"], fit["measured_c"], predicted_c):
                writer.writerow((depth, measured, predicted, measured - predicted))
        self.status_var.set(f"Report saved to {path}")

    def _export_plot(self) -> None:
        if self.figure is None:
            if self.graph_mode.get() == "arrhenius":
                self._draw_arrhenius_chart()
            elif self.loaded_data is not None or self.current_result is not None:
                self._draw_chart()
        if self.figure is None:
            messagebox.showinfo("Export graph", "Plot a graph first.", parent=self.root)
            return
        window = tk.Toplevel(self.root)
        window.title("Export graph")
        window.configure(bg=self.p["card"])
        window.transient(self.root)
        window.resizable(True, True)
        self._lbl(window, "Choose the figure size for a presentation.", bg="card", fg="ink", size=11, bold=True).pack(anchor="w", padx=16, pady=(16, 8))
        grid = self._frame(window, "card")
        grid.pack(fill="x", padx=16)
        for column in range(3):
            grid.grid_columnconfigure(column, weight=1)
        self._lbl(grid, "Width (in)", bg="card", fg="muted", size=9).grid(row=0, column=0, sticky="w")
        self._lbl(grid, "Height (in)", bg="card", fg="muted", size=9).grid(row=0, column=1, sticky="w", padx=(8, 0))
        self._lbl(grid, "DPI", bg="card", fg="muted", size=9).grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Entry(grid, textvariable=self.export_width_in).grid(row=1, column=0, sticky="ew")
        ttk.Entry(grid, textvariable=self.export_height_in).grid(row=1, column=1, sticky="ew", padx=(8, 0))
        ttk.Entry(grid, textvariable=self.export_dpi).grid(row=1, column=2, sticky="ew", padx=(8, 0))
        preview = tk.StringVar(value="")

        def update_preview(*_args) -> None:
            try:
                width = float(self.export_width_in.get())
                height = float(self.export_height_in.get())
                dpi = float(self.export_dpi.get())
                preview.set(f"{width * dpi:.0f} × {height * dpi:.0f} pixels")
            except ValueError:
                preview.set("Enter width, height, and DPI.")

        self.export_width_in.trace_add("write", update_preview)
        self.export_height_in.trace_add("write", update_preview)
        self.export_dpi.trace_add("write", update_preview)
        update_preview()
        self._lbl(window, bg="card", fg="muted", size=9, textvariable=preview).pack(anchor="w", padx=16, pady=(8, 0))

        def save() -> None:
            try:
                width = float(self.export_width_in.get())
                height = float(self.export_height_in.get())
                dpi = float(self.export_dpi.get())
                if width <= 0 or height <= 0 or dpi <= 0:
                    raise ValueError("Width, height, and DPI must be positive.")
            except ValueError as error:
                messagebox.showerror("Export graph", str(error), parent=window)
                return
            path = filedialog.asksaveasfilename(
                parent=window,
                title="Save graph image",
                defaultextension=".png",
                initialfile=f"{self._default_export_stem()}.png",
                filetypes=[("PNG image", "*.png"), ("SVG image", "*.svg"), ("PDF document", "*.pdf")],
            )
            if not path:
                return
            original = self.figure.get_size_inches().copy()
            try:
                self.figure.set_size_inches(width, height)
                self.figure.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=self.figure.get_facecolor())
            except OSError as error:
                messagebox.showerror("Could not save plot", str(error), parent=window)
                return
            finally:
                self.figure.set_size_inches(original)
                self.canvas.draw_idle()
            self.status_var.set(f"Graph saved to {path}  ·  {width:g}×{height:g} in at {dpi:g} dpi")
            window.destroy()

        button_row = self._frame(window, "card")
        button_row.pack(fill="x", padx=16, pady=16)
        self._button(button_row, "Save image", save, kind="accent").pack(side="right")
        self._button(button_row, "Cancel", window.destroy, kind="tool").pack(side="right", padx=(0, 8))

    def _arrhenius_points(self) -> list[dict]:
        points = []
        for profile_id in self.profile_order:
            profile = self.profiles[profile_id]
            result = profile.get("result")
            fit = profile.get("fit_data") or {}
            temperature = fit.get("temperature_K")
            if temperature is None:
                try:
                    raw = profile.get("temperature_k") or ""
                    temperature = float(raw) if str(raw).strip() else None
                except ValueError:
                    temperature = None
            if result is None or temperature is None:
                continue
            sigma = result.D_err if result.D_err and math.isfinite(result.D_err) and result.D_err > 0 else None
            if sigma is None:
                rmse = getattr(result, "rmse", 0.0) or 0.0
                span = abs((fit.get("C_s") or 0.0) - (fit.get("C_0") or 0.0)) or 1.0
                sigma = abs(result.D) * (rmse / span) if rmse > 0 else None
            if sigma is None:
                continue
            try:
                ln_D, ln_err = arrhenius.ln_diffusion_error(result.D, sigma)
                x = arrhenius.inv_kT(temperature)
            except ValueError:
                continue
            points.append(
                {
                    "label": profile.get("label", profile_id),
                    "T": temperature,
                    "D": result.D,
                    "D_err": sigma,
                    "x": x,
                    "y": ln_D,
                    "y_err": ln_err,
                }
            )
        return points

    def _fit_arrhenius(self) -> None:
        points = self._arrhenius_points()
        if len(points) < 2:
            messagebox.showinfo(
                "1/kT plot",
                "Fit at least two sheets, each with a temperature and a diffusivity error, then linearize.\n\n"
                "σ_ln(D) = σ_D / D. Those errors set the slope and intercept uncertainties.",
                parent=self.root,
            )
            return
        try:
            self.arrhenius_fit = arrhenius.fit_ln_vs_inv_kT(
                [point["T"] for point in points],
                [point["D"] for point in points],
                [point["D_err"] for point in points],
            )
        except ValueError as error:
            messagebox.showerror("1/kT plot", str(error), parent=self.root)
            return
        self._set_graph_mode("arrhenius")
        line = self.arrhenius_fit
        self.status_var.set(
            f"ln(D) vs 1/kT  ·  slope = {line.slope:.5g} ± {line.slope_err:.5g}  ·  "
            f"E_a = {line.activation_eV:.5g} ± {line.activation_err:.5g} eV"
        )

    def _draw_arrhenius_chart(self) -> None:
        points = self._arrhenius_points()
        self._draw_generation += 1
        self._clear_chart_widgets()
        self.figure = None
        self.canvas = None
        self.toolbar = None
        width = max(self.chart_host.winfo_width(), 640)
        height = max(self.chart_host.winfo_height() - 36, 360)
        dpi = 110
        p = self.p
        self.figure = Figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor=p["card"])
        ax = self.figure.add_subplot(111)
        self.figure.subplots_adjust(left=0.1, right=0.98, bottom=0.14, top=0.96)
        ax.set_facecolor(p["card"])
        ax.grid(True, color=p["grid"], linewidth=0.7)
        ax.tick_params(colors=p["muted"], labelsize=8, length=0)
        for spine_name, spine in ax.spines.items():
            spine.set_color(p["line"])
            if spine_name in ("top", "right"):
                spine.set_visible(False)
        self.chart_title_var.set("Graph 2  ·  ln(D) vs 1/kT")
        if not points:
            self.chart_subtitle_var.set("Fit two or more sheets at different temperatures, then Fit 1/kT line.")
            ax.text(0.5, 0.5, "Need two fitted sheets with T and σ_D", ha="center", va="center", transform=ax.transAxes, color=p["muted"])
        else:
            x = np.array([point["x"] for point in points], dtype=float)
            y = np.array([point["y"] for point in points], dtype=float)
            y_err = np.array([point["y_err"] for point in points], dtype=float)
            ax.errorbar(x, y, yerr=y_err, fmt="o", color=p["point"], ecolor=p["muted"], capsize=3, label="ln(D) ± σ_D/D")
            line = self.arrhenius_fit
            if line is not None:
                span = np.linspace(float(np.min(x)), float(np.max(x)), 80)
                ax.plot(span, line.intercept + line.slope * span, color=p["curve"], linewidth=2.2, label="Weighted line")
                note = (
                    f"slope  {line.slope:.4g} ± {line.slope_err:.3g}\n"
                    f"intercept  {line.intercept:.4g} ± {line.intercept_err:.3g}\n"
                    f"σ_ln / |ln| and σ_m / |m|, σ_b / |b|\n"
                    f"rel. slope  {line.slope_rel:.3g}   rel. intercept  {line.intercept_rel:.3g}\n"
                    f"E_a  {line.activation_eV:.4g} ± {line.activation_err:.3g} eV"
                )
                ax.text(
                    0.03,
                    0.97,
                    note,
                    transform=ax.transAxes,
                    va="top",
                    fontsize=10,
                    color=p["ink"],
                    bbox={"boxstyle": "round,pad=0.5", "facecolor": p["card"], "edgecolor": p["accent"], "alpha": 0.96},
                )
                self.chart_subtitle_var.set(
                    f"{len(points)} points   ·   ln(D) = ln(D₀) − E_a / kT   ·   R² = {line.r_squared:.4f}"
                )
            else:
                self.chart_subtitle_var.set(f"{len(points)} points   ·   Fit 1/kT line for slope and intercept errors")
            for point in points:
                ax.annotate(point["label"], (point["x"], point["y"]), textcoords="offset points", xytext=(6, 4), fontsize=8, color=p["muted"])
        ax.set_xlabel("1/kT  (eV⁻¹)", color=p["ink"], fontsize=9)
        ax.set_ylabel("ln(D)", color=p["ink"], fontsize=9)
        legend = ax.legend(frameon=False, loc="best", fontsize=8)
        if legend:
            for text in legend.get_texts():
                text.set_color(p["ink"])
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.chart_host)
        self.canvas.draw()
        widget = self.canvas.get_tk_widget()
        widget.configure(bg=p["card"])
        self.toolbar = NavigationToolbar2Tk(self.canvas, self.chart_host, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side="bottom", fill="x")
        widget.pack(side="top", fill="both", expand=True)
        if points:
            arr_x = np.array([point["x"] for point in points], dtype=float)
            arr_y = np.array([point["y"] for point in points], dtype=float)

            def format_arrhenius_point(index: int) -> str:
                point = points[index]
                return (
                    f"{point['label']}\n"
                    f"1/kT  {point['x']:.5g} eV⁻¹\n"
                    f"ln(D)  {point['y']:.5g} ± {point['y_err']:.3g}"
                )

            self._attach_plot_hover(ax, arr_x, arr_y, format_arrhenius_point)
        self._set_export_enabled(True)
        self.root.after_idle(self._sync_figure_size)

    def _refresh_project_tree(self) -> None:
        if not hasattr(self, "explorer"):
            return
        selected = self.active_profile_id
        self._refreshing_tree = True
        self.explorer.delete(*self.explorer.get_children())
        books = self.explorer.insert("", "end", iid="folder-books", text="Workbooks", open=True)
        graphs = self.explorer.insert("", "end", iid="folder-graphs", text="Graphs", open=True)
        for profile_id in self.profile_order:
            label = self.profiles[profile_id].get("label", profile_id)
            self.explorer.insert(books, "end", iid=profile_id, text=label)
        self.explorer.insert(graphs, "end", iid="graph-profile", text="Graph 1 · Profile")
        self.explorer.insert(graphs, "end", iid="graph-arrhenius", text="Graph 2 · ln(D) vs 1/kT")
        if selected and self.explorer.exists(selected):
            self.explorer.selection_set(selected)
        self._refreshing_tree = False

    def _on_project_select(self, _event=None) -> None:
        if self._refreshing_tree or not hasattr(self, "explorer"):
            return
        picked = self.explorer.selection()
        if not picked:
            return
        item = picked[0]
        if item in self.profiles:
            self._select_profile(item)
        elif item == "graph-profile":
            self._set_graph_mode("profile")
        elif item == "graph-arrhenius":
            self._set_graph_mode("arrhenius")

    def _refresh_workbook(self) -> None:
        if not hasattr(self, "workbook"):
            return
        self.workbook.delete(*self.workbook.get_children())
        raw = self.loaded_data
        if raw is None:
            return
        depths, concentrations = raw
        predicted = None
        if self.current_result is not None and self.current_fit_data is not None:
            predicted = scenario1.concentration(
                np.asarray(depths, dtype=float) * self._depth_scale(),
                self.current_result.D,
                self.current_fit_data["t"],
                self.current_fit_data["C_s"],
                self.current_fit_data["C_0"],
            )
        for index, (depth, concentration) in enumerate(zip(depths, concentrations), start=1):
            model = ""
            residual = ""
            if predicted is not None:
                model = f"{predicted[index - 1]:.6g}"
                residual = f"{concentration - predicted[index - 1]:.6g}"
            self.workbook.insert("", "end", values=(index, f"{depth:.8g}", f"{concentration:.8g}", model, residual))

    def _edit_workbook_cell(self, event) -> None:
        row_id = self.workbook.identify_row(event.y)
        column = self.workbook.identify_column(event.x)
        if not row_id or column not in ("#2", "#3"):
            return
        bbox = self.workbook.bbox(row_id, column)
        if not bbox:
            return
        x, y, width, height = bbox
        value_index = 1 if column == "#2" else 2
        current = self.workbook.set(row_id, "depth" if value_index == 1 else "concentration")
        entry = ttk.Entry(self.workbook)
        entry.place(x=x, y=y, width=width, height=height)
        entry.insert(0, current)
        entry.focus_set()

        def commit(_event=None) -> None:
            text = entry.get().strip()
            try:
                number = float(text)
            except ValueError:
                entry.destroy()
                return
            values = list(self.workbook.item(row_id, "values"))
            values[value_index] = f"{number:.8g}"
            self.workbook.item(row_id, values=values)
            entry.destroy()
            self._apply_workbook()

        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)

    def _apply_workbook(self) -> None:
        depths = []
        concentrations = []
        for row_id in self.workbook.get_children():
            values = self.workbook.item(row_id, "values")
            try:
                depths.append(float(values[1]))
                concentrations.append(float(values[2]))
            except (ValueError, IndexError):
                continue
        if len(depths) < 2:
            return
        self.loaded_data = (np.asarray(depths, dtype=float), np.asarray(concentrations, dtype=float))
        self.current_result = None
        self.current_fit_data = None
        self._save_active_profile()
        self._clear_metrics()
        self._refresh_summary()
        self._set_graph_mode("profile")
        self.status_var.set("Workbook applied. Fit again to refresh D.")

    def _paste_workbook(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("Paste table", "Copy a two-column table first.", parent=self.root)
            return
        depths = []
        concentrations = []
        for line in text.replace(";", "\t").replace(",", "\t").splitlines():
            parts = [piece.strip() for piece in line.split("\t") if piece.strip()]
            if len(parts) < 2:
                continue
            try:
                depths.append(float(parts[0]))
                concentrations.append(float(parts[1]))
            except ValueError:
                continue
        if len(depths) < 2:
            messagebox.showerror("Paste table", "Need at least two numeric depth, concentration rows.", parent=self.root)
            return
        self.loaded_data = (np.asarray(depths, dtype=float), np.asarray(concentrations, dtype=float))
        self.loaded_headers = ["depth", "concentration"]
        self.file_var.set("(pasted workbook)")
        self.current_result = None
        self.current_fit_data = None
        self._clear_metrics()
        self._save_active_profile()
        self.show_workbook.set(True)
        self._sync_panes()
        self._refresh_workbook()
        self._refresh_summary()
        self._set_graph_mode("profile")
        self.status_var.set(f"Pasted {len(depths)} rows into the workbook.")


def main() -> None:
    root = tk.Tk()
    DiffusionApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
