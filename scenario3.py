"""Scenario 3: brute-force C_s and fit D for each candidate.

For each sampled C_s in [0, minimum measured concentration], this script fits
D to the semi-infinite Dirichlet solution

    C(x, t) = C_0 + (C_s - C_0) * erfc(x / (2 * sqrt(D * t)))

and selects the C_s, D pair with the lowest sum of squared residuals. C_s is
not found by an algebraic or multivariable equation solve; it is selected by a
grid search, then a finer grid between the winning candidate and its neighbors.
Increase --cs-steps for a finer C_s grid.

Example:
    python scenario3.py example.csv --time 360000 --c0 100
"""

import argparse
import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import erfc

from scenario1 import fit_diffusion_coefficient, load_csv, plot_fit


@dataclass
class FitResult:
    """Best grid-search fit and the resolution used to search C_s."""

    D: float
    D_err: float
    C_s: float
    C_s_grid_step: float
    r_squared: float
    rmse: float
    at_lower_bound: bool = False
    at_upper_bound: bool = False
    search_high: float = 0.0


def _far_field_concentration(x, measured_C):
    """Median concentration among the deepest measurements."""
    order = np.argsort(x)
    count = max(3, measured_C.size // 10)
    return float(np.median(measured_C[order[-count:]]))


def _length_sse(x, measured_C, C_s, C_0):
    """Best diffusion-length sum of squares for one fixed surface concentration."""
    delta = float(C_s - C_0)
    positive_depths = x[x > 0]
    guess = math.log(max(float(np.median(positive_depths)), 1e-12))

    def objective(log_length):
        predicted = C_0 + delta * erfc(x / math.exp(log_length))
        residual = measured_C - predicted
        return float(residual @ residual)

    span = 8.0
    solved = None
    for _ in range(5):
        solved = minimize_scalar(
            objective,
            bounds=(guess - span, guess + span),
            method="bounded",
            options={"xatol": 1e-8},
        )
        if guess - span + 1e-5 < solved.x < guess + span - 1e-5:
            break
        span *= 2.0
    return float(solved.fun)


def _best_on_grid(x, measured_C, candidates, C_0):
    """Return the candidate C_s with the smallest concentration residual."""
    best_score = float("inf")
    best_C_s = None
    for C_s in candidates:
        # No concentration contrast, so D cannot be identified.
        if np.isclose(C_s, C_0):
            continue
        try:
            score = _length_sse(x, measured_C, float(C_s), C_0)
        except (ValueError, RuntimeError, FloatingPointError, OverflowError):
            continue
        if score < best_score:
            best_score = score
            best_C_s = float(C_s)
    return best_C_s, best_score


def fit_by_brute_force(x, measured_C, t, C_0, cs_steps=1001):
    """Search C_s from zero to min(measured_C), fitting D at each grid value."""
    x = np.asarray(x, dtype=float)
    measured_C = np.asarray(measured_C, dtype=float)
    if x.ndim != 1 or measured_C.ndim != 1 or x.shape != measured_C.shape:
        raise ValueError("depths and concentrations must be 1-D arrays of equal length")
    if measured_C.size < 2:
        raise ValueError("at least two data points are required")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(measured_C)):
        raise ValueError("depths and concentrations must be finite")
    if np.any(x < 0):
        raise ValueError("depths must be non-negative")
    if not math.isfinite(t) or t <= 0:
        raise ValueError("time must be a finite positive value")
    if not math.isfinite(C_0):
        raise ValueError("C_0 must be finite")
    if not np.any(x > 0):
        raise ValueError("at least one measurement depth must be greater than zero")
    if int(cs_steps) < 2:
        raise ValueError("cs_steps must be at least 2")
    if int(cs_steps) > 20000:
        raise ValueError("cs_steps must be 20000 or fewer")
    minimum_concentration = float(np.min(measured_C))
    if minimum_concentration <= 0:
        raise ValueError(
            "Scenario 3 searches C_s from 0 up to the lowest measured concentration, "
            f"so every concentration has to be positive. The lowest value here is {minimum_concentration:.6g}."
        )

    model_low = min(0.0, float(C_0))
    model_high = max(minimum_concentration, float(C_0))
    padding = 0.08 * max(float(np.ptp(measured_C)), abs(float(C_0)), 1.0)
    outside = np.mean((measured_C < model_low - padding) | (measured_C > model_high + padding))
    if outside > 0.35:
        far_field = _far_field_concentration(x, measured_C)
        raise ValueError(
            "Scenario 3 cannot represent this profile with the current bulk concentration. "
            f"It only tries surface values from 0 to {minimum_concentration:.6g}, and with "
            f"C_0 = {C_0:.6g} the model stays inside that range. "
            f"{outside:.0%} of the measurements fall outside it. "
            f"The deepest points cluster near {far_field:.6g}, which is the usual value to enter for C_0. "
            "If the surface concentration is higher than the measurements, use Scenario 2 instead."
        )

    coarse = np.linspace(0.0, minimum_concentration, int(cs_steps))
    best_C_s, best_score = _best_on_grid(x, measured_C, coarse, C_0)
    if best_C_s is None:
        raise ValueError(
            "no valid fit found in the requested C_s range; check t, C_0, "
            "the input data, and the selected search interval"
        )

    nearest = int(np.argmin(np.abs(coarse - best_C_s)))
    low_index = max(nearest - 1, 0)
    high_index = min(nearest + 1, coarse.size - 1)
    fine = np.linspace(float(coarse[low_index]), float(coarse[high_index]), int(cs_steps))
    refined_C_s, refined_score = _best_on_grid(x, measured_C, fine, C_0)
    if refined_C_s is not None and refined_score <= best_score:
        best_C_s = refined_C_s
    grid_step = float(fine[1] - fine[0]) if fine.size > 1 else float(coarse[1] - coarse[0])

    best_result = fit_diffusion_coefficient(x, measured_C, t, best_C_s, C_0)
    edge = max(grid_step * 0.51, minimum_concentration * 1e-9)
    return FitResult(
        D=best_result.D,
        D_err=best_result.D_err,
        C_s=best_C_s,
        C_s_grid_step=grid_step,
        r_squared=best_result.r_squared,
        rmse=best_result.rmse,
        at_lower_bound=best_C_s <= edge,
        at_upper_bound=best_C_s >= minimum_concentration - edge,
        search_high=minimum_concentration,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Brute-force C_s and fit D from a semi-infinite concentration profile."
    )
    parser.add_argument("csv", help="CSV with depth and concentration columns")
    parser.add_argument("--time", "-t", type=float, required=True, help="known diffusion time")
    parser.add_argument("--c0", type=float, required=True, help="known initial/bulk concentration C_0")
    parser.add_argument("--x-col", default="0", help="depth column index or header name")
    parser.add_argument("--c-col", default="1", help="concentration column index or header name")
    parser.add_argument(
        "--x-scale",
        type=float,
        default=1.0,
        help="multiply depths by this factor before fitting (e.g. 1e-3 for mm to m)",
    )
    parser.add_argument(
        "--cs-steps",
        type=int,
        default=1001,
        help="number of brute-force C_s values from 0 to min(measured C) (default: 1001)",
    )
    parser.add_argument(
        "--plot",
        default="scenario3_fit.png",
        help="file path for the measured-points and fitted-curve plot",
    )
    args = parser.parse_args(argv)

    x, measured_C = load_csv(args.csv, args.x_col, args.c_col)
    x = x * args.x_scale
    result = fit_by_brute_force(x, measured_C, args.time, args.c0, args.cs_steps)
    print(f"Points fitted: {x.size}")
    print(f"Known values: t={args.time:g}, C_0={args.c0:g}")
    print(f"C_s search: 0 to {float(np.min(measured_C)):g} in {args.cs_steps} steps")
    print(f"D   = {result.D:.5e} +/- {result.D_err:.2e} (depth unit)^2/time unit")
    print(f"C_s = {result.C_s:.6g} (grid step {result.C_s_grid_step:.3g}; concentration units)")
    print(f"R^2 = {result.r_squared:.5f}; RMSE = {result.rmse:.5g}")
    if result.at_lower_bound:
        print("Note: best C_s is on the lower edge of the search (0). The profile may want a surface value below 0.")
    plot_fit(x, measured_C, result, args.time, result.C_s, args.c0, args.plot)
    print(f"Plot saved to: {args.plot}")
    return result


if __name__ == "__main__":
    main()
