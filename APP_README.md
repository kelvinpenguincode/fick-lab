# FickLab desktop app

FickLab is a Windows desktop interface for the three semi-infinite Fick's second-law fitting methods. It loads measured depth/concentration data, plots the measured points with the fitted profile, and exports plots and fit summaries.

## Start the app

- Double-click `run_app.bat` to run the current Python source when Python is installed; it falls back to `dist/FickLab.exe` otherwise. Double-click `dist/FickLab.exe` to always run the standalone build.
- To build the standalone executable on Windows, double-click `build_exe.bat`. When it finishes, the executable is `dist/FickLab.exe`.
- To run from Python, open a terminal in the project folder, install `requirements-app.txt` with `python -m pip install -r requirements-app.txt`, then launch `python diffusion_app.py`.
- On Windows, double-click `run_python.bat` to launch the Python source directly without using the packaged executable.

The first executable build needs an internet connection to install dependencies and may take several minutes. The resulting one-file executable bundles Python and the scientific libraries; Python is not needed on the target computer. A Windows executable must be built on Windows.

## Use the interface

1. The window is laid out like Origin: Project explorer, setup, Graph 1 / Graph 2, and a workbook table. Import one or more CSV sheets, or paste a table with Ctrl+V.
2. Enter diffusion time in **hours**. The app converts to seconds for the Fick fit so D is in (depth unit)²/s.
3. Set C₀, depth scale, and temperature (K or °C). Fit D on Graph 1. Fit at least two sheets, then open Graph 2 and linearize ln(D) vs 1/kT (`k = 8.617333262e-5 eV/K`). σ_ln(D) = σ_D / D; that residual error sets the slope and intercept uncertainties.
4. **Export graph** asks for width, height, and DPI so the figure matches a presentation.
5. Press **F1** for the in-app tutorial. **Check for updates** replaces the Start menu copy when a newer GitHub release exists.

The input panel can be vertically scrolled on shorter displays. The Run Fit button stays pinned at the bottom of the panel. The window opens at about 90% of the detected screen, can be resized, and has a draggable divider between setup and analysis. Fit cards reflow automatically as the analysis area narrows. Use fullscreen with F11 if desired.

Keyboard shortcuts: Ctrl+O opens CSV profiles, Enter or Ctrl+Enter fits the active profile, Ctrl+Shift+S exports its chart, and F11 toggles fullscreen. The File, View, and Help menus provide import/export, appearance, fullscreen, shortcuts, and model assumptions.

## Share the app and results

- After rebuilding, share `dist/FickLab.exe`. It is a single Windows executable with Python and the required libraries bundled; recipients do not need Python installed. Send the input CSV separately if they need to repeat your analysis. The executable is about 70 MB, so a cloud link or ZIP attachment may be more convenient than email.
- This EXE is for Windows. To share with macOS or Linux users, build a separate executable on that operating system.
- To share an analysis result, export both the plot image and the results CSV. The CSV contains the fit parameters, units/settings, input filename, and each measured value alongside its model prediction and residual.
- Windows may show a SmartScreen warning because the app is not code-signed. Recipients should only run it when they trust the person who shared it.

### Scenarios

- **Scenario 1 — known C_s:** same as `scenario1.py`; C_s and C_0 are fixed, and nonlinear fitting estimates D only.
- **Scenario 2 — Newton–Raphson (D, C_s):** same as `scenario2.py`; multivariable Newton–Raphson estimates D and C_s together from the measured profile. Only t and C_0 are fixed inputs.
- **Scenario 3 — brute-force C_s grid:** same as `scenario3.py`; test the configured number of C_s candidates from zero through the minimum measured concentration, fit D for every candidate, and keep the pair with the smallest sum of squared errors. C_s is limited by grid spacing and this search interval, and can land on an endpoint.

All scenarios use the semi-infinite constant-surface-concentration profile:

    C(x,t) = C_0 + (C_s - C_0) * erfc(x / (2 * sqrt(D * t)))

## Data file support

Comma-separated CSV is supported, as are tab-, semicolon-, and pipe-delimited text files (including tab-separated spreadsheet files saved with a `.csv` extension). Header rows are optional. The first two columns are selected automatically by default; use the column selectors for other columns. All selected fields must contain finite numbers. Avoid thousands separators in numeric fields; decimal values should use a period.

## Publishing an update

Put `owner/repository` on one line in `github_repo.txt`, then raise `APP_VERSION` in `app_version.py`. Commit both, and push a tag such as `v1.2.0`. The GitHub Action builds `FickLab.exe` and attaches it to that release. People who already have the app press **Check for updates** and install that file. The release version has to be higher than the version baked into their exe.
