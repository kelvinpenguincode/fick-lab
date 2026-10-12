"""Scenario 1: fit D for a semi-infinite solid when C_s is known.

The concentration profile uses the constant-surface-concentration Dirichlet
solution of Fick's second law:

    C(x, t) = C_0 + (C_s - C_0) * erfc(x / (2 * sqrt(D * t)))

Only D is fitted. Supply the known exposure time, surface concentration, and
initial/bulk concentration on the command line. Depth and time units determine
the units of D (for example, metres and seconds give m^2/s).

Example:
    python scenario1.py example.csv --time 36000 --cs 100 --c0 0
"""

import argparse
import csv
import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import curve_fit
from scipy.special import erfc


@dataclass
class FitResult:
    """Estimated diffusion coefficient and goodness-of-fit statistics."""

    D: float
    D_err: float
    r_squared: float
    rmse: float


def concentration(x, D, t, C_s, C_0):
    """Calculate concentration at depth x using the semi-infinite solution."""
    if not math.isfinite(D) or D <= 0:
        raise ValueError("D must be a finite positive value")
    if not math.isfinite(t) or t <= 0:
        raise ValueError("time must be a finite positive value")
    x = np.asarray(x, dtype=float)
    if np.any(x < 0):
        raise ValueError("depths must be non-negative")
    return C_0 + (C_s - C_0) * erfc(x / (2.0 * np.sqrt(D * t)))


def load_csv(path, x_col=0, c_col=1):
    """Read depth and concentration columns from a delimited file.

    A header row is optional. Comma-, tab-, semicolon-, and pipe-delimited
    spreadsheet exports are detected automatically, including tab-delimited
    files that were saved with a .csv extension.
    """
    with open(path, newline="", encoding="utf-8-sig") as csv_file:
        sample = csv_file.read(8192)
        csv_file.seek(0)
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
        rows = [
            row for row in csv.reader(csv_file, delimiter=delimiter)
            if row and row[0].strip()
        ]
    if not rows:
        raise ValueError(f"{path} contains no data")

    header = None
    try:
        float(rows[0][0])
    except ValueError:
        header = [value.strip() for value in rows.pop(0)]

    def resolve_column(column):
        if isinstance(column, int) or str(column).lstrip("-").isdigit():
            return int(column)
        if header is None or column not in header:
            raise ValueError(f"column {column!r} not found in CSV header {header}")
        return header.index(column)

    x_index = resolve_column(x_col)
    c_index = resolve_column(c_col)
    try:
        x = np.asarray([float(row[x_index]) for row in rows], dtype=float)
        measured_C = np.asarray([float(row[c_index]) for row in rows], dtype=float)
    except (ValueError, IndexError) as error:
        raise ValueError("CSV must contain numeric depth and concentration columns") from error
    return x, measured_C


def fit_diffusion_coefficient(x, measured_C, t, C_s, C_0):
    """Fit only D while holding t, C_s, and C_0 at their supplied values."""
    x = np.asarray(x, dtype=float)
    measured_C = np.asarray(measured_C, dtype=float)
    if x.ndim != 1 or measured_C.ndim != 1 or x.shape != measured_C.shape:
        raise ValueError("depths and concentrations must be 1-D arrays of equal length")
    if x.size < 2:
        raise ValueError("at least two data points are required to fit D")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(measured_C)):
        raise ValueError("depths and concentrations must be finite")
    if np.any(x < 0):
        raise ValueError("depths must be non-negative")
    if not math.isfinite(t) or t <= 0:
        raise ValueError("time must be a finite positive value")
    if not math.isfinite(C_s) or not math.isfinite(C_0):
        raise ValueError("C_s and C_0 must be finite values")
    if math.isclose(C_s, C_0):
        raise ValueError("C_s and C_0 must differ to identify D from the profile")
    if not np.any(x > 0):
        raise ValueError("at least one measurement depth must be greater than zero")

    # Fit the diffusion length L = 2*sqrt(D*t), which is on the scale of x.
    # This is numerically better conditioned than fitting small D directly.
    positive_depths = x[x > 0]
    initial_length = float(np.median(positive_depths))

    def model(depth, length):
        return C_0 + (C_s - C_0) * erfc(depth / length)

    (length,), covariance = curve_fit(
        model,
        x,
        measured_C,
        p0=(initial_length,),
        bounds=((np.finfo(float).tiny,), (np.inf,)),
        maxfev=20000,
    )
    length_err = math.sqrt(max(float(covariance[0, 0]), 0.0))
    D = length**2 / (4.0 * t)
    D_err = D * 2.0 * length_err / length

    residuals = measured_C - model(x, length)
    sum_squared_residuals = float(np.sum(residuals**2))
    sum_squared_total = float(np.sum((measured_C - measured_C.mean()) ** 2))
    return FitResult(
        D=float(D),
        D_err=float(D_err),
        r_squared=(
            1.0 - sum_squared_residuals / sum_squared_total
            if sum_squared_total > 0
            else float("nan")
        ),
        rmse=float(np.sqrt(sum_squared_residuals / x.size)),
    )


def plot_fit(x, measured_C, result, t, C_s, C_0, output_path):
    """Save measured concentration points overlaid with the fitted curve."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = np.asarray(x, dtype=float)
    curve_x = np.linspace(0.0, float(np.max(x)), 400)
    curve_C = concentration(curve_x, result.D, t, C_s, C_0)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(x, measured_C, color="#1f4e79", s=42, label="Measured data", zorder=3)
    ax.plot(
        curve_x,
        curve_C,
        color="#d1495b",
        linewidth=3.2,
        label="Fitted Fick's law curve",
        zorder=4,
    )
    ax.set_xlabel("Depth x (input depth units)")
    ax.set_ylabel("Normalized concentration (%)")
    ax.set_title("Semi-infinite diffusion profile")
    ax.grid(True, alpha=0.3)
    ax.legend()

    x_range = float(np.ptp(x)) or 1.0
    y_range = float(np.ptp(measured_C)) or 1.0
    normalized_x = (x - float(np.min(x))) / x_range
    normalized_y = (measured_C - float(np.min(measured_C))) / y_range
    corner_regions = {
        "upper left": (0.02, 0.98, "left", "top", normalized_x <= 0.35, normalized_y >= 0.65),
        "upper right": (0.98, 0.98, "right", "top", normalized_x >= 0.65, normalized_y >= 0.65),
        "lower left": (0.02, 0.02, "left", "bottom", normalized_x <= 0.35, normalized_y <= 0.35),
        "lower right": (0.98, 0.02, "right", "bottom", normalized_x >= 0.65, normalized_y <= 0.35),
    }
    corner = min(
        corner_regions,
        key=lambda name: np.count_nonzero(
            corner_regions[name][4] & corner_regions[name][5]
        ),
    )
    text_x, text_y, horizontal_alignment, vertical_alignment, *_ = corner_regions[corner]
    annotation = f"D = {result.D:.4e}\n$R^2$ = {result.r_squared:.5f}"
    if hasattr(result, "C_s"):
        annotation = f"D = {result.D:.4e}\nC_s = {result.C_s:.4g}\n$R^2$ = {result.r_squared:.5f}"
    ax.text(
        text_x,
        text_y,
        annotation,
        transform=ax.transAxes,
        ha=horizontal_alignment,
        va=vertical_alignment,
        bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.9},
    )
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Scenario 1: fit D when C_s is known, using Fick's second law."
    )
    parser.add_argument("csv", help="CSV with depth and concentration columns")
    parser.add_argument("--time", "-t", type=float, required=True, help="known diffusion time")
    parser.add_argument("--cs", type=float, required=True, help="known surface concentration C_s")
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
        "--plot",
        default="scenario1_fit.png",
        help="file path for the measured-points and fitted-curve plot",
    )
    args = parser.parse_args(argv)

    x, measured_C = load_csv(args.csv, args.x_col, args.c_col)
    x = x * args.x_scale
    result = fit_diffusion_coefficient(x, measured_C, args.time, args.cs, args.c0)
    print(f"Points fitted: {x.size}")
    print(f"Known values: t={args.time:g}, C_s={args.cs:g}, C_0={args.c0:g}")
    print(f"D = {result.D:.5e} +/- {result.D_err:.2e} (depth unit)^2/time unit")
    print(f"R^2 = {result.r_squared:.5f}; RMSE = {result.rmse:.5g}")
    plot_fit(x, measured_C, result, args.time, args.cs, args.c0, args.plot)
    print(f"Plot saved to: {args.plot}")
    return result


if __name__ == "__main__":
    main()
