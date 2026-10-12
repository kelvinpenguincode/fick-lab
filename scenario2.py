"""Scenario 2: fit both D and C_s from a semi-infinite diffusion profile.

The known values are exposure time t and bulk/initial concentration C_0. The
measured (x, C) data are fit to the Dirichlet solution

    C(x, t) = C_0 + (C_s - C_0) * erfc(x / (2 * sqrt(D * t)))

using a multivariable Newton–Raphson iteration to estimate both D and C_s.
Newton's method is applied to the gradient of the sum-of-squared-residuals
objective, updating [log(L), C_s] together, where L = 2*sqrt(D*t). A line
search damps steps that would otherwise increase the residual error.

Example:
    python scenario2.py example.csv --time 36000 --c0 100
"""

import argparse
import math
from dataclasses import dataclass

import numpy as np
from scipy.special import erfc

from scenario1 import load_csv, plot_fit


@dataclass
class FitResult:
    """Estimated D and C_s, with uncertainty and fit quality statistics."""

    D: float
    D_err: float
    C_s: float
    C_s_err: float
    r_squared: float
    rmse: float


def fit_parameters(x, measured_C, t, C_0):
    """Estimate D and C_s while holding time t and bulk concentration C_0 fixed.

    Multivariable Newton–Raphson minimizes half the sum of squared residuals
    in parameters [log(L), C_s], with L = 2*sqrt(D*t). Using log(L) ensures
    the implied diffusion length stays positive. D is recovered after fitting.
    """
    x = np.asarray(x, dtype=float)
    measured_C = np.asarray(measured_C, dtype=float)
    if x.ndim != 1 or measured_C.ndim != 1 or x.shape != measured_C.shape:
        raise ValueError("depths and concentrations must be 1-D arrays of equal length")
    if x.size < 3:
        raise ValueError("at least three data points are required to fit D and C_s")
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
    if np.ptp(measured_C) <= np.finfo(float).eps * max(1.0, abs(float(measured_C.mean()))):
        raise ValueError("concentrations must vary with depth to estimate D and C_s")

    order = np.argsort(x)
    x = x[order]
    measured_C = measured_C[order]
    positive_depths = x[x > 0]
    initial_length = float(np.median(positive_depths))
    initial_C_s = float(measured_C[0])
    if math.isclose(initial_C_s, C_0):
        initial_C_s = float(measured_C.max() if measured_C.max() != C_0 else measured_C.min())

    parameters = np.asarray([math.log(initial_length), initial_C_s], dtype=float)
    erfc_scale = 2.0 / math.sqrt(math.pi)

    def objective_gradient_hessian(current_parameters):
        """Return half-SSE, its gradient, exact Hessian, residuals, and Jacobian."""
        log_length, C_s = current_parameters
        length = math.exp(float(log_length))
        u = x / length
        exp_term = np.exp(-(u**2))
        erfc_term = erfc(u)
        concentration_delta = C_s - C_0
        predicted = C_0 + concentration_delta * erfc_term
        residuals = predicted - measured_C

        # First and second model derivatives for parameters [log(L), C_s].
        dC_dlogL = concentration_delta * erfc_scale * u * exp_term
        dC_dCs = erfc_term
        d2C_dlogL2 = concentration_delta * erfc_scale * u * exp_term * (2.0 * u**2 - 1.0)
        d2C_dlogL_dCs = erfc_scale * u * exp_term
        jacobian = np.column_stack((dC_dlogL, dC_dCs))

        gradient = jacobian.T @ residuals
        hessian = jacobian.T @ jacobian
        hessian[0, 0] += float(np.sum(residuals * d2C_dlogL2))
        mixed_second_derivative = float(np.sum(residuals * d2C_dlogL_dCs))
        hessian[0, 1] += mixed_second_derivative
        hessian[1, 0] += mixed_second_derivative
        objective = 0.5 * float(residuals @ residuals)
        return objective, gradient, hessian, residuals, jacobian

    converged = False
    for _ in range(200):
        objective, gradient, hessian, residuals, jacobian = objective_gradient_hessian(parameters)
        if np.linalg.norm(gradient, ord=np.inf) <= 1e-10 * max(1.0, math.sqrt(2.0 * objective)):
            converged = True
            break

        # Newton step: H * delta = -gradient. Add diagonal damping only if
        # the Hessian does not produce a finite descent direction.
        diagonal_scale = np.maximum(np.abs(np.diag(hessian)), 1e-12)
        damping_values = [0.0] + [10.0**power for power in range(-10, 9)]
        direction = None
        for damping in damping_values:
            try:
                candidate_direction = np.linalg.solve(
                    hessian + damping * np.diag(diagonal_scale), -gradient
                )
            except np.linalg.LinAlgError:
                continue
            if np.all(np.isfinite(candidate_direction)) and gradient @ candidate_direction < 0.0:
                direction = candidate_direction
                break
        if direction is None:
            raise RuntimeError("Newton-Raphson could not find a descent direction")

        # Backtracking line search keeps the Newton iteration from increasing SSE.
        accepted = False
        step_scale = 1.0
        for _ in range(50):
            candidate_parameters = parameters + step_scale * direction
            if -700.0 < candidate_parameters[0] < 700.0:
                candidate_objective = objective_gradient_hessian(candidate_parameters)[0]
                if candidate_objective < objective:
                    accepted = True
                    break
            step_scale *= 0.5
        if not accepted:
            if np.linalg.norm(gradient, ord=np.inf) <= 1e-8 * max(1.0, math.sqrt(2.0 * objective)):
                converged = True
                break
            raise RuntimeError("Newton-Raphson line search failed to reduce the fit error")

        parameters = candidate_parameters
        if np.linalg.norm(step_scale * direction) <= 1e-10 * (1.0 + np.linalg.norm(parameters)):
            converged = True
            break

    if not converged:
        raise RuntimeError("Newton-Raphson did not converge within 200 iterations")

    objective, gradient, hessian, residuals, jacobian = objective_gradient_hessian(parameters)
    log_length, C_s = parameters
    length = math.exp(float(log_length))
    degrees_of_freedom = max(x.size - 2, 1)
    residual_variance = float(np.sum(residuals**2)) / degrees_of_freedom
    try:
        covariance = np.linalg.inv(jacobian.T @ jacobian) * residual_variance
        standard_errors = np.sqrt(np.maximum(np.diag(covariance), 0.0))
        log_length_err, C_s_err = standard_errors
    except np.linalg.LinAlgError:
        log_length_err, C_s_err = float("inf"), float("inf")

    D = length**2 / (4.0 * t)
    D_err = 2.0 * D * float(log_length_err)

    sum_squared_residuals = float(np.sum(residuals**2))
    sum_squared_total = float(np.sum((measured_C - measured_C.mean()) ** 2))
    return FitResult(
        D=float(D),
        D_err=float(D_err),
        C_s=float(C_s),
        C_s_err=float(C_s_err),
        r_squared=(
            1.0 - sum_squared_residuals / sum_squared_total
            if sum_squared_total > 0
            else float("nan")
        ),
        rmse=float(np.sqrt(sum_squared_residuals / x.size)),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Scenario 2: fit both D and C_s from a semi-infinite diffusion profile."
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
        "--plot",
        default="scenario2_fit.png",
        help="file path for the measured-points and fitted-curve plot",
    )
    args = parser.parse_args(argv)

    x, measured_C = load_csv(args.csv, args.x_col, args.c_col)
    x = x * args.x_scale
    result = fit_parameters(x, measured_C, args.time, args.c0)
    print(f"Points fitted: {x.size}")
    print(f"Known values: t={args.time:g}, C_0={args.c0:g}")
    print(f"D   = {result.D:.5e} +/- {result.D_err:.2e} (depth unit)^2/time unit")
    print(f"C_s = {result.C_s:.6g} +/- {result.C_s_err:.3g} (concentration units)")
    print(f"R^2 = {result.r_squared:.5f}; RMSE = {result.rmse:.5g}")
    plot_fit(x, measured_C, result, args.time, result.C_s, args.c0, args.plot)
    print(f"Plot saved to: {args.plot}")
    return result


if __name__ == "__main__":
    main()
