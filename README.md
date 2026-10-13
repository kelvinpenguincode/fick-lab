# FickLab

FickLab is an Origin-style Windows workbench for Fick’s second law (semi-infinite solid, fixed surface concentration) and Arrhenius plots of diffusivity.

```
C(x, t) = C₀ + (Cₛ − C₀) · erfc( x / (2 √(Dt)) )
```

Open the installed app from the Start menu or the desktop shortcut. That copy is the one updates replace.

## Tutorial

1. **Import a workbook.** File → Import workbook (Ctrl+O), or paste a two-column depth / concentration table (Ctrl+V). Each CSV is a sheet in the Project explorer. Double-click a workbook cell to edit it, then Apply table to plot.

2. **Enter time in hours.** The fit converts hours to seconds automatically (`1 h = 3600 s`). Diffusivity is reported in (depth unit)² / s.

3. **Fit D.** Set C₀, depth scale, and a scenario, then Fit D or press Enter. Graph 1 is the measured profile, the fitted erfc curve, and residuals.

4. **Linearize ln(D) vs 1/kT.** Set temperature in kelvin (or °C) on each fitted sheet. Open Graph 2 and Fit 1/kT line.

   - Boltzmann constant `k = 8.617333262 × 10⁻⁵ eV/K`
   - x-axis: `1/(kT)` in eV⁻¹
   - y-axis: `ln(D)`
   - Error of the natural log: `σ_ln(D) = σ_D / D` (divide the diffusivity error by D itself)
   - Those y-errors weight the line. Slope and intercept errors come from that residual.
   - Relative errors: `σ_slope / |slope|` and `σ_intercept / |intercept|`
   - Arrhenius form: `ln(D) = ln(D₀) − E_a · (1/kT)`, so slope = `−E_a` (eV)

5. **Export a graph.** Export graph asks for width, height (inches), and DPI so the image matches a presentation slide. PNG, SVG, and PDF are supported.

6. **Help in the app.** Press F1 or Help → Tutorial.

## Scenarios

- **Scenario 1 — known Cₛ.** Fit D only.
- **Scenario 2 — Newton–Raphson.** Fit D and Cₛ together.
- **Scenario 3 — brute-force Cₛ grid.** Search Cₛ from 0 through the lowest measured concentration and keep the lowest error.

## Download and updates

Releases: https://github.com/kelvinpenguincode/fick-lab/releases

People who already have FickLab use **Updates** in the app. Publish a higher `APP_VERSION`, push `main`, then push a `v*` tag. GitHub builds `FickLab.exe` and attaches it to the release.

## Run from source

```
python -m pip install -r requirements-app.txt
python launch_splash.py
```

Or double-click `run_app.bat`. Build a Windows exe with `build_exe.bat`.
