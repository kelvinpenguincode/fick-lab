#!/usr/bin/env python3
"""Fit a concentration-depth profile to Fick's second law (semi-infinite solid,
constant surface concentration / Dirichlet boundary) and recover D and C_s.

Model
-----
    dC/dt = D * d2C/dx2
    C(0, t)   = C_s      (fixed surface concentration)
    C(x, 0)   = C_0      (uniform initial concentration)
    C(inf, t) = C_0

    =>  C(x, t) = C_s - (C_s - C_0) * erf( x / (2 * sqrt(D * t)) )

Known: the data points (x, C), the diffusion time t, and C_0.
Fitted: D and C_s.

Usage
-----
    python fick_fit.py data/example.csv --time 36000 --c0 0.2
    python fick_fit.py --demo
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.optimize import curve_fit
from scipy.special import erf


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------
def concentration(x, D, C_s, t, C_0=0.0):
    """Concentration at depth x after time t (semi-infinite solid)."""
    x = np.asarray(x, dtype=float)
    return C_s - (C_s - C_0) * erf(x / (2.0 * np.sqrt(D * t)))


def _model_L(x, L, C_s, C_0):
    """Same model written with the diffusion length L = 2*sqrt(D*t).

    Fitting L instead of D keeps both parameters near order 1-ish relative to
    the data, which makes the optimiser far more reliable (D itself is often
    ~1e-11, which is a terrible number to hand to a least-squares solver).
    """
    return C_s - (C_s - C_0) * erf(x / L)


# --------------------------------------------------------------------------
# Fit
# --------------------------------------------------------------------------
@dataclass
class FitResult:
    D: float          # diffusion coefficient, [x unit]^2 / [t unit]
    D_err: float      # 1-sigma standard error
    C_s: float        # surface concentration, same unit as C
    C_s_err: float    # 1-sigma standard error
    L: float          # diffusion length 2*sqrt(D*t), same unit as x
    r_squared: float
    rmse: float
    t: float
    C_0: float


def fit_profile(x, C, t, C_0=0.0, sigma=None) -> FitResult:
    """Least-squares fit of D and C_s to measured (x, C) points.

    x     : depths (any length unit; D comes out in that unit squared / time)
    C     : measured concentrations
    t     : diffusion time (any time unit; D comes out per that unit)
    C_0   : known initial / bulk concentration
    sigma : optional per-point measurement uncertainties in C
    """
    x = np.asarray(x, dtype=float)
    C = np.asarray(C, dtype=float)
    if x.shape != C.shape or x.ndim != 1:
        raise ValueError("x and C must be 1-D arrays of the same length")
    if x.size < 3:
        raise ValueError("need at least 3 data points to fit 2 parameters")
    if np.any(x < 0):
        raise ValueError("depths must be >= 0 (x = 0 is the surface)")
    if t <= 0:
        raise ValueError("time must be positive")

    order = np.argsort(x)
    x, C = x[order], C[order]
    if sigma is not None:
        sigma = np.asarray(sigma, dtype=float)[order]

    # Initial guesses: C_s ~ the shallowest reading; L ~ depth where the
    # profile has dropped about halfway to C_0 (erf(0.477) = 0.5).
    Cs0 = C[0]
    if np.isclose(Cs0, C_0):
        raise ValueError("data near the surface equals C_0 - nothing to fit")
    frac = (C - C_0) / (Cs0 - C_0)
    below = np.where(frac <= 0.5)[0]
    x_half = x[below[0]] if below.size else x[-1]
    L0 = max(x_half, x[x > 0].min()) / 0.477

    f = lambda xx, L, C_s: _model_L(xx, L, C_s, C_0)
    popt, pcov = curve_fit(
        f, x, C, p0=[L0, Cs0], sigma=sigma,
        absolute_sigma=sigma is not None,
        bounds=([1e-300, -np.inf], [np.inf, np.inf]),
    )
    L, C_s = popt
    L_err, C_s_err = np.sqrt(np.diag(pcov))

    D = L**2 / (4.0 * t)
    D_err = D * 2.0 * L_err / L          # error propagation: D ~ L^2

    resid = C - f(x, L, C_s)
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((C - C.mean()) ** 2))
    return FitResult(
        D=D, D_err=D_err, C_s=C_s, C_s_err=C_s_err, L=L,
        r_squared=1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan"),
        rmse=float(np.sqrt(ss_res / x.size)),
        t=t, C_0=C_0,
    )


# --------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------
def load_csv(path, x_col=0, c_col=1):
    """Read two numeric columns from a CSV. A header row is skipped
    automatically; columns can be given by index or by header name."""
    with open(path, newline="") as fh:
        rows = [r for r in csv.reader(fh) if r and not r[0].lstrip().startswith("#")]
    if not rows:
        raise ValueError(f"{path} is empty")

    header = None
    try:
        float(rows[0][0])
    except ValueError:
        header, rows = [h.strip() for h in rows[0]], rows[1:]

    def resolve(col):
        if isinstance(col, int) or str(col).lstrip("-").isdigit():
            return int(col)
        if header is None or col not in header:
            raise ValueError(f"column {col!r} not found; header is {header}")
        return header.index(col)

    xi, ci = resolve(x_col), resolve(c_col)
    x = np.array([float(r[xi]) for r in rows])
    C = np.array([float(r[ci]) for r in rows])
    return x, C


def make_demo_data(seed=0):
    """Synthetic carburising-style data with known answers, for testing.
    True values: D = 1.6e-11 m^2/s, C_s = 1.0 wt%, C_0 = 0.2 wt%, t = 10 h."""
    rng = np.random.default_rng(seed)
    t, C_0, D_true, Cs_true = 36000.0, 0.2, 1.6e-11, 1.0
    x = np.linspace(0.0, 3.0e-3, 16)                      # metres
    C = concentration(x, D_true, Cs_true, t, C_0) + rng.normal(0, 0.012, x.size)
    return x, C, t, C_0, D_true, Cs_true


def plot_fit(x, C, res: FitResult, out_path, x_label="x", c_label="C",
             d_unit="", title=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = np.linspace(0.0, max(x) * 1.05, 400)
    fig, (ax, axr) = plt.subplots(
        2, 1, figsize=(7, 6), sharex=True,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08},
    )
    ax.plot(x, C, "o", color="#1f3b73", label="Measured")
    ax.plot(xs, concentration(xs, res.D, res.C_s, res.t, res.C_0),
            "-", color="#d1495b", lw=2, label="Fick's 2nd law fit")
    ax.axhline(res.C_0, color="gray", ls=":", lw=1, label=f"$C_0$ = {res.C_0:g}")
    ax.set_ylabel(c_label)
    ax.set_title(title or "Semi-infinite diffusion profile fit")
    ax.legend(loc="upper right")
    ax.text(
        0.03, 0.06,
        f"$D$ = {res.D:.3e} ± {res.D_err:.1e} {d_unit}\n"
        f"$C_s$ = {res.C_s:.4g} ± {res.C_s_err:.2g}\n"
        f"$R^2$ = {res.r_squared:.4f}",
        transform=ax.transAxes, va="bottom", ha="left",
        bbox=dict(boxstyle="round", fc="white", ec="lightgray"),
    )
    ax.grid(alpha=0.3)

    axr.axhline(0, color="gray", lw=1)
    axr.plot(x, C - concentration(x, res.D, res.C_s, res.t, res.C_0),
             "o", color="#1f3b73", ms=4)
    axr.set_xlabel(x_label)
    axr.set_ylabel("Residual")
    axr.grid(alpha=0.3)

    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(
        description="Fit D and C_s from a concentration-depth profile "
                    "(Fick's 2nd law, semi-infinite solid, constant surface concentration).")
    p.add_argument("csv", nargs="?", help="CSV file with depth and concentration columns")
    p.add_argument("--time", "-t", type=float, help="diffusion time (e.g. seconds)")
    p.add_argument("--c0", type=float, default=0.0,
                   help="initial/bulk concentration C_0 (default 0)")
    p.add_argument("--x-col", default="0", help="depth column: index or header name (default 0)")
    p.add_argument("--c-col", default="1", help="concentration column: index or header name (default 1)")
    p.add_argument("--x-scale", type=float, default=1.0,
                   help="multiply depths by this before fitting, e.g. 1e-3 to turn mm into m")
    p.add_argument("--x-unit", default="m", help="depth unit after scaling, for labels (default m)")
    p.add_argument("--t-unit", default="s", help="time unit, for labels (default s)")
    p.add_argument("--c-unit", default="", help="concentration unit, for labels")
    p.add_argument("--plot", default="fit.png", help="output plot file (default fit.png)")
    p.add_argument("--no-plot", action="store_true", help="skip the plot")
    p.add_argument("--demo", action="store_true", help="run on built-in synthetic data")
    a = p.parse_args(argv)

    if a.demo:
        x, C, t, C_0, D_true, Cs_true = make_demo_data()
        print(f"Demo data: true D = {D_true:.3e} m^2/s, true C_s = {Cs_true}")
        a.c_unit = a.c_unit or "wt%"
    else:
        if not a.csv or a.time is None:
            p.error("give a CSV file and --time (or use --demo)")
        x, C = load_csv(a.csv, a.x_col, a.c_col)
        x, t, C_0 = x * a.x_scale, a.time, a.c0

    res = fit_profile(x, C, t, C_0)
    d_unit = f"{a.x_unit}²/{a.t_unit}"
    cu = f" {a.c_unit}" if a.c_unit else ""

    print(f"Points fitted : {len(x)}")
    print(f"t = {t:g} {a.t_unit},  C_0 = {C_0:g}{cu}")
    print(f"D   = {res.D:.4e} ± {res.D_err:.1e} {d_unit}")
    print(f"C_s = {res.C_s:.4f} ± {res.C_s_err:.4f}{cu}")
    print(f"Diffusion length 2*sqrt(D*t) = {res.L:.4e} {a.x_unit}")
    print(f"R^2 = {res.r_squared:.5f},  RMSE = {res.rmse:.4g}{cu}")
    if x.max() < res.L:
        print("Warning: data do not reach one diffusion length - "
              "D is poorly constrained; measure deeper if you can.", file=sys.stderr)

    if not a.no_plot:
        plot_fit(x, C, res, a.plot,
                 x_label=f"Depth x ({a.x_unit})",
                 c_label=f"Concentration{f' ({a.c_unit})' if a.c_unit else ''}",
                 d_unit=d_unit)
        print(f"Plot saved to {Path(a.plot).resolve()}")
    return res


if __name__ == "__main__":
    main()
