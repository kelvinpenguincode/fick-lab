"""Run with:  python -m pytest   (or just: python test_fick_fit.py)"""
import numpy as np

from fick_fit import concentration, fit_profile, make_demo_data


def test_recovers_exact_parameters():
    t, C_0, D, C_s = 3600.0, 0.1, 2.5e-12, 0.8
    x = np.linspace(0, 5e-4, 12)
    res = fit_profile(x, concentration(x, D, C_s, t, C_0), t, C_0)
    assert np.isclose(res.D, D, rtol=1e-6)
    assert np.isclose(res.C_s, C_s, rtol=1e-6)


def test_recovers_noisy_parameters_within_error():
    x, C, t, C_0, D_true, Cs_true = make_demo_data()
    res = fit_profile(x, C, t, C_0)
    assert abs(res.D - D_true) < 3 * res.D_err
    assert abs(res.C_s - Cs_true) < 3 * res.C_s_err


def test_boundary_conditions():
    assert np.isclose(concentration(0.0, 1e-11, 1.0, 100.0, 0.2), 1.0)
    assert np.isclose(concentration(1.0, 1e-11, 1.0, 100.0, 0.2), 0.2)


def test_unit_independence():
    """Same data in mm should give D in mm^2/s = 1e6 x the m^2/s value."""
    x, C, t, C_0, *_ = make_demo_data()
    assert np.isclose(fit_profile(x * 1e3, C, t, C_0).D,
                      fit_profile(x, C, t, C_0).D * 1e6, rtol=1e-5)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
