"""Arrhenius linearization: ln(D) versus 1/(kT).

k is the Boltzmann constant in eV/K. Diffusion time is entered in hours and
converted to seconds before Fick fitting so D is reported in (depth unit)²/s.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

K_BOLTZMANN_EV = 8.617333262e-5  # eV/K
SECONDS_PER_HOUR = 3600.0


def hours_to_seconds(hours: float) -> float:
    if not math.isfinite(hours) or hours <= 0:
        raise ValueError("Diffusion time in hours must be a positive number.")
    return hours * SECONDS_PER_HOUR


def inv_kT(temperature_K: float) -> float:
    """Return 1/(kT) in eV⁻¹."""
    if not math.isfinite(temperature_K) or temperature_K <= 0:
        raise ValueError("Temperature must be a positive value in kelvin.")
    return 1.0 / (K_BOLTZMANN_EV * temperature_K)


def celsius_to_kelvin(celsius: float) -> float:
    return celsius + 273.15


def kelvin_to_celsius(kelvin: float) -> float:
    return kelvin - 273.15


def ln_diffusion_error(D: float, D_err: float) -> tuple[float, float]:
    """Natural log of D and its error.

    Error of ln(D) is the relative error of D: σ_ln(D) = σ_D / D.
    Divide the diffusivity error by D itself, not by the error of D.
    """
    if not math.isfinite(D) or D <= 0:
        raise ValueError("Diffusivity must be a positive number before taking ln(D).")
    if not math.isfinite(D_err) or D_err < 0:
        raise ValueError("Diffusivity error must be a finite non-negative number.")
    return math.log(D), D_err / D


@dataclass
class LineFit:
    """y = intercept + slope * x, with y-errors from σ_ln(D) = σ_D / D."""

    slope: float
    intercept: float
    slope_err: float
    intercept_err: float
    slope_rel: float
    intercept_rel: float
    r_squared: float
    rmse: float
    x: np.ndarray
    y: np.ndarray
    y_err: np.ndarray
    activation_eV: float
    activation_err: float
    D0: float
    D0_err: float


def _relative(error: float, value: float) -> float:
    if not math.isfinite(value) or value == 0:
        return float("nan")
    return abs(error / value)


def fit_ln_vs_inv_kT(temperatures_K, diffusivities, diffusivity_errors) -> LineFit:
    """Weighted line through ln(D) vs 1/(kT).

    The residual (or reported) error of each D becomes the y-error of ln(D)
    after dividing by D. Those y-errors weight the slope and intercept, and
    the line residual is scaled into σ_slope and σ_intercept.
    """
    T = np.asarray(temperatures_K, dtype=float)
    D = np.asarray(diffusivities, dtype=float)
    sigma_D = np.asarray(diffusivity_errors, dtype=float)
    if T.size < 2 or T.size != D.size or T.size != sigma_D.size:
        raise ValueError("The 1/kT plot needs at least two (T, D, σ_D) points of equal length.")
    if np.any(T <= 0) or np.any(D <= 0) or np.any(~np.isfinite(T)) or np.any(~np.isfinite(D)):
        raise ValueError("Temperature and diffusivity must be finite and positive.")
    sigma_D = np.where(np.isfinite(sigma_D) & (sigma_D > 0), sigma_D, np.nan)
    if np.any(~np.isfinite(sigma_D)):
        raise ValueError("Each diffusivity needs a positive residual error before linearizing.")

    x = 1.0 / (K_BOLTZMANN_EV * T)
    y = np.log(D)
    y_err = sigma_D / D
    weights = 1.0 / np.square(y_err)
    design = np.column_stack((np.ones(x.size), x))
    weighted = design.T * weights
    gram = weighted @ design
    try:
        gram_inv = np.linalg.inv(gram)
    except np.linalg.LinAlgError as error:
        raise ValueError("The 1/kT points are not independent enough to fit a line.") from error
    beta = gram_inv @ (weighted @ y)
    intercept, slope = float(beta[0]), float(beta[1])
    predicted = intercept + slope * x
    residual = y - predicted
    degrees = max(x.size - 2, 1)
    chi_squared = float(np.sum(weights * residual**2))
    scale = chi_squared / degrees
    covariance = gram_inv * scale
    intercept_err = math.sqrt(max(float(covariance[0, 0]), 0.0))
    slope_err = math.sqrt(max(float(covariance[1, 1]), 0.0))
    ss_tot = float(np.sum(weights * (y - np.average(y, weights=weights)) ** 2))
    r_squared = 1.0 - chi_squared / ss_tot if ss_tot > 0 else float("nan")
    rmse = float(np.sqrt(np.mean(residual**2)))
    activation = -slope
    D0 = math.exp(intercept)
    D0_err = D0 * intercept_err
    return LineFit(
        slope=slope,
        intercept=intercept,
        slope_err=slope_err,
        intercept_err=intercept_err,
        slope_rel=_relative(slope_err, slope),
        intercept_rel=_relative(intercept_err, intercept),
        r_squared=r_squared,
        rmse=rmse,
        x=x,
        y=y,
        y_err=y_err,
        activation_eV=activation,
        activation_err=slope_err,
        D0=D0,
        D0_err=D0_err,
    )
