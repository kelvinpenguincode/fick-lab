# fick_fit

Fits a concentration-vs-depth profile to the solution of Fick's second law for a
semi-infinite solid with a constant surface concentration (Dirichlet boundary),
and returns the diffusion coefficient **D** and surface concentration **C_s**.

## Model

    C(x, t) = C_s - (C_s - C_0) * erf( x / (2 * sqrt(D * t)) )

| Symbol | Meaning | Known or fitted |
|---|---|---|
| x, C | measured depth and concentration | known (your data) |
| t | diffusion time | known (`--time`) |
| C_0 | initial / bulk concentration | known (`--c0`, default 0) |
| D | diffusion coefficient | **fitted** |
| C_s | surface concentration | **fitted** |

## Setup

    pip install -r requirements.txt

## Use

Put your data in a CSV with a depth column and a concentration column
(header row optional):

    depth_m,concentration_wtpct
    0.0,1.0015
    0.0002,0.8789
    ...

Then run:

    python fick_fit.py data/example.csv --time 36000 --c0 0.2 --c-unit "wt%"

This prints D and C_s with 1-sigma standard errors, R^2 and RMSE, and saves
`fit.png` (data, fitted curve, residuals).

Try it without any data: `python fick_fit.py --demo`

### Units

D comes out in (depth unit)^2 / (time unit). If depth is in metres and time in
seconds, D is in m^2/s. If your depths are in mm or um, either keep them and
read D in mm^2/s or um^2/s, or convert on the way in:

    python fick_fit.py mydata.csv -t 36000 --x-scale 1e-6     # um -> m

### Options

| Flag | Purpose |
|---|---|
| `--time`, `-t` | diffusion time (required) |
| `--c0` | initial/bulk concentration (default 0) |
| `--x-col`, `--c-col` | column index or header name (defaults 0 and 1) |
| `--x-scale` | multiply depths by this before fitting |
| `--x-unit`, `--t-unit`, `--c-unit` | labels only |
| `--plot FILE` / `--no-plot` | plot output |
| `--demo` | run on built-in synthetic data |

### From your own code

    from fick_fit import fit_profile
    res = fit_profile(x, C, t=36000, C_0=0.2)
    print(res.D, res.D_err, res.C_s, res.C_s_err, res.r_squared)

## Notes

- The fit is done on the diffusion length L = 2*sqrt(D*t) rather than D
  directly, then converted. D is often ~1e-11, which least-squares solvers
  handle badly; L is on the same scale as your depths.
- D is only well determined if your data reach roughly one diffusion length
  or deeper. The script warns if they don't.
- The model assumes D is constant, the solid is effectively infinitely thick
  (thickness >> L), and the starting concentration is uniform.

## Tests

    python test_fick_fit.py      # or: python -m pytest
