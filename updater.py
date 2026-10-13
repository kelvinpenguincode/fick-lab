"""Look up the newest FickLab.exe on GitHub and replace the running build."""

from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app_version import APP_VERSION, GITHUB_REPOSITORY


@dataclass
class ReleaseInfo:
    version: str
    notes: str
    download_url: str
    page_url: str
    newer: bool


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def install_directory() -> Path:
    override = os.environ.get("FICKLAB_HOME", "").strip()
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "FickLab"


def installed_executable() -> Path:
    return install_directory() / "FickLab.exe"


def _version_file() -> Path:
    return install_directory() / "version.txt"


def _recorded_version() -> str:
    try:
        return _version_file().read_text(encoding="ascii").strip()
    except OSError:
        return "0"


def remember_install() -> None:
    """Refresh shortcuts and record this build when this process is the installed exe."""
    if not getattr(sys, "frozen", False):
        return
    current = Path(sys.executable).resolve()
    target = installed_executable()
    if current != target.resolve():
        return
    install_directory().mkdir(parents=True, exist_ok=True)
    _version_file().write_text(APP_VERSION + "\n", encoding="ascii")
    ensure_shortcuts(target)


def should_handoff() -> bool:
    """A downloaded or old copy should open the Start-menu install instead."""
    if not getattr(sys, "frozen", False):
        return False
    current = Path(sys.executable).resolve()
    target = installed_executable()
    return current != target.resolve()


def publish_installed_copy() -> Path:
    """Place this exe where the shortcuts point, without replacing a newer install."""
    target = installed_executable()
    target.parent.mkdir(parents=True, exist_ok=True)
    source = Path(sys.executable).resolve()
    installed = _recorded_version()
    if (not target.exists()) or is_newer(APP_VERSION, installed):
        shutil.copy2(source, target)
        _version_file().write_text(APP_VERSION + "\n", encoding="ascii")
    ensure_shortcuts(target)
    return target


def launch_installed() -> None:
    target = installed_executable()
    _detached([str(target)], target.parent)


def ensure_shortcuts(target: Path) -> None:
    """Desktop and Start menu shortcuts. Search for FickLab in the Start menu."""
    target = target.resolve()
    command = """
$desktop = [Environment]::GetFolderPath('Desktop')
$start = Join-Path $env:APPDATA 'Microsoft\\Windows\\Start Menu\\Programs'
New-Item -ItemType Directory -Force -Path $start | Out-Null
$shell = New-Object -ComObject WScript.Shell
foreach ($path in @(
    (Join-Path $desktop 'FickLab.lnk'),
    (Join-Path $start 'FickLab.lnk')
)) {
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $env:FICKLAB_TARGET
    $shortcut.WorkingDirectory = Split-Path $env:FICKLAB_TARGET
    $shortcut.Description = 'FickLab'
    $shortcut.WindowStyle = 1
    $shortcut.Save()
}
"""
    environment = os.environ.copy()
    environment["FICKLAB_TARGET"] = str(target)
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=20,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "shortcut creation failed").strip()
        raise RuntimeError(detail)


def install_executable(source: Path, version: str) -> Path:
    """Copy a built exe into the Start-menu location. Used after a local build."""
    target = installed_executable()
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    _version_file().write_text(version.strip() + "\n", encoding="ascii")
    ensure_shortcuts(target)
    return target


def bundled_directory() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent


def read_repository() -> str:
    """Prefer a github_repo.txt beside the exe, then the copy bundled inside it."""
    candidates = [
        application_directory() / "github_repo.txt",
        bundled_directory() / "github_repo.txt",
    ]
    for path in candidates:
        repo = _repository_in_file(path)
        if repo:
            return repo
    return GITHUB_REPOSITORY.strip()


def _repository_in_file(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        text = line.strip()
        if text and not text.startswith("#") and "/" in text and " " not in text:
            return text
    return ""


def parse_version(text: str) -> tuple[int, ...]:
    body = text.strip().lstrip("vV")
    numbers: list[int] = []
    for piece in body.split("."):
        digits = ""
        for character in piece:
            if character.isdigit():
                digits += character
            else:
                break
        if not digits:
            break
        numbers.append(int(digits))
    return tuple(numbers) or (0,)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


def latest_release() -> ReleaseInfo:
    repository = read_repository()
    if not repository:
        raise RuntimeError(
            "Updates are published as GitHub releases, and this build does not name a repository yet.\n\n"
            "Put one line in github_repo.txt, next to FickLab.exe or in the project folder:\n"
            "    your-github-name/your-repository\n\n"
            "Then publish a release whose tag is a higher version than "
            f"{APP_VERSION}, with FickLab.exe attached."
        )
    url = f"https://api.github.com/repos/{repository}/releases/latest"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "FickLab-updater",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30, context=ssl.create_default_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise RuntimeError(
                f"GitHub has no latest release for {repository}. Publish a release and attach FickLab.exe."
            ) from error
        raise RuntimeError(f"GitHub returned HTTP {error.code} while checking {repository}.") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach GitHub. {error.reason}") from error

    tag = str(payload.get("tag_name") or payload.get("name") or "")
    assets = payload.get("assets") or []
    download_url = ""
    for asset in assets:
        name = str(asset.get("name") or "")
        if name.lower() == "ficklab.exe":
            download_url = str(asset.get("browser_download_url") or "")
            break
    if not download_url:
        raise RuntimeError(
            f"Release {tag or '(untitled)'} does not include a file named FickLab.exe."
        )
    return ReleaseInfo(
        version=tag.lstrip("vV") or tag,
        notes=str(payload.get("body") or "").strip(),
        download_url=download_url,
        page_url=str(payload.get("html_url") or f"https://github.com/{repository}/releases/latest"),
        newer=is_newer(tag),
    )


def download_exe(url: str, progress) -> Path:
    destination = Path(tempfile.gettempdir()) / "FickLab-update.exe"
    request = urllib.request.Request(url, headers={"User-Agent": "FickLab-updater"})
    with urllib.request.urlopen(request, timeout=120, context=ssl.create_default_context()) as response:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        with destination.open("wb") as handle:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                received += len(chunk)
                progress(received / total if total else None, total or received)
    with destination.open("rb") as handle:
        signature = handle.read(2)
    if signature != b"MZ" or destination.stat().st_size < 1_000_000:
        destination.unlink(missing_ok=True)
        raise RuntimeError("GitHub did not return the FickLab program. The download was left unused.")
    return destination


CREATE_BREAKAWAY_FROM_JOB = 0x01000000
CREATE_NEW_CONSOLE = 0x00000010


def _detached(command: list[str], folder: Path) -> None:
    """Start a helper that keeps running after this windowed exe exits."""
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    subprocess.Popen(
        command,
        cwd=str(folder),
        close_fds=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=startup,
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP
            | CREATE_NEW_CONSOLE
            | CREATE_BREAKAWAY_FROM_JOB
        ),
    )


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def schedule_replacement(downloaded: Path, pid: int | None = None, version: str | None = None) -> None:
    """Replace the installed exe after this process exits, then open that copy."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Open FickLab.exe to install an update. The Python source is not replaced automatically.")
    target = installed_executable()
    target.parent.mkdir(parents=True, exist_ok=True)
    script = install_directory() / "apply-update.ps1"
    log = install_directory() / "update.log"
    pid = os.getpid() if pid is None else pid
    downloaded = downloaded.resolve()
    running = Path(sys.executable).resolve()
    version_text = (version or "").strip()
    # The packaged app is two FickLab.exe processes. Waiting only for this PID
    # left the bootloader locking the file, so the copy failed and nothing relaunched.
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    body = f"""$ErrorActionPreference = 'Continue'
$appPid = {int(pid)}
$target = {_ps_quote(str(target))}
$running = {_ps_quote(str(running))}
$downloaded = {_ps_quote(str(downloaded))}
$log = {_ps_quote(str(log))}
$version = {_ps_quote(version_text)}
function Write-Log($message) {{
    Add-Content -LiteralPath $log -Value $message -Encoding ascii
}}
function Get-FickLabHolders {{
    $found = @()
    $byId = Get-Process -Id $appPid -ErrorAction SilentlyContinue
    if ($byId) {{ $found += $byId }}
    $named = Get-Process -Name FickLab -ErrorAction SilentlyContinue
    foreach ($proc in @($named)) {{
        if ($proc -and ($found | Where-Object {{ $_.Id -eq $proc.Id }}).Count -eq 0) {{
            $found += $proc
        }}
    }}
    return $found
}}
Set-Content -LiteralPath $log -Value "waiting for $appPid" -Encoding ascii
$form = $null
$detail = $null
if ($env:FICKLAB_UPDATE_SILENT -ne '1') {{
    try {{
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        $form = New-Object System.Windows.Forms.Form
        $form.Text = 'FickLab'
        $form.FormBorderStyle = 'FixedSingle'
        $form.StartPosition = 'CenterScreen'
        $form.ClientSize = New-Object System.Drawing.Size(560, 220)
        $form.BackColor = [System.Drawing.Color]::FromArgb(15, 23, 42)
        $form.ForeColor = [System.Drawing.Color]::FromArgb(248, 250, 252)
        $form.TopMost = $true
        $form.ControlBox = $false
        $form.MaximizeBox = $false
        $form.MinimizeBox = $false
        $title = New-Object System.Windows.Forms.Label
        $title.Text = 'Installing the update'
        $title.Font = New-Object System.Drawing.Font('Segoe UI', 18, [System.Drawing.FontStyle]::Bold)
        $title.ForeColor = [System.Drawing.Color]::FromArgb(248, 250, 252)
        $title.BackColor = $form.BackColor
        $title.AutoSize = $false
        $title.Size = New-Object System.Drawing.Size(500, 40)
        $title.Location = New-Object System.Drawing.Point(30, 36)
        $detail = New-Object System.Windows.Forms.Label
        $detail.Text = 'FickLab will reopen from the Start menu shortcut.'
        $detail.Font = New-Object System.Drawing.Font('Segoe UI', 11)
        $detail.ForeColor = [System.Drawing.Color]::FromArgb(148, 163, 184)
        $detail.BackColor = $form.BackColor
        $detail.AutoSize = $false
        $detail.Size = New-Object System.Drawing.Size(500, 48)
        $detail.Location = New-Object System.Drawing.Point(30, 88)
        $bar = New-Object System.Windows.Forms.ProgressBar
        $bar.Style = 'Marquee'
        $bar.MarqueeAnimationSpeed = 30
        $bar.Size = New-Object System.Drawing.Size(500, 8)
        $bar.Location = New-Object System.Drawing.Point(30, 160)
        $form.Controls.Add($title)
        $form.Controls.Add($detail)
        $form.Controls.Add($bar)
        $form.Show()
        [System.Windows.Forms.Application]::DoEvents()
    }} catch {{
        $form = $null
        Write-Log ("window " + $_.Exception.Message)
    }}
}}
function Pump {{
    if ($form -ne $null) {{
        [System.Windows.Forms.Application]::DoEvents()
    }}
}}
$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline) {{
    $holders = @(Get-FickLabHolders)
    if ($holders.Count -eq 0) {{ break }}
    Pump
    Start-Sleep -Milliseconds 300
}}
$leftover = @(Get-FickLabHolders)
foreach ($proc in $leftover) {{
    Write-Log ("stop " + $proc.ProcessId)
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
}}
Start-Sleep -Milliseconds 800
Pump
Write-Log 'replacing'
if ($detail -ne $null) {{
    $detail.Text = 'Replacing the installed FickLab...'
    Pump
}}
$copied = $false
for ($attempt = 1; $attempt -le 80; $attempt++) {{
    try {{
        if (Test-Path -LiteralPath $target) {{
            Move-Item -LiteralPath $target -Destination ($target + '.old') -Force -ErrorAction Stop
        }}
        Copy-Item -LiteralPath $downloaded -Destination $target -Force -ErrorAction Stop
        $copied = $true
        break
    }} catch {{
        Write-Log ("retry " + $attempt + " " + $_.Exception.Message)
        Pump
        Start-Sleep -Milliseconds 400
    }}
}}
function Start-Installed {{
    try {{
        Start-Process -FilePath $target -WorkingDirectory (Split-Path -Parent $target)
        Write-Log 'launched'
        return $true
    }} catch {{
        Write-Log ("start failed " + $_.Exception.Message)
        try {{
            cmd.exe /c start "" $target
            Write-Log 'launched-cmd'
            return $true
        }} catch {{
            Write-Log ("cmd start failed " + $_.Exception.Message)
            return $false
        }}
    }}
}}
if ($copied) {{
    if ($version -ne '') {{
        $versionFile = Join-Path (Split-Path -Parent $target) 'version.txt'
        Set-Content -LiteralPath $versionFile -Value $version -Encoding ascii
    }}
    Remove-Item -LiteralPath ($target + '.old') -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $downloaded -Force -ErrorAction SilentlyContinue
    Write-Log 'starting'
    Start-Installed | Out-Null
    if ($form -ne $null) {{ $form.Close() }}
    exit 0
}}
Write-Log 'failed'
$old = $target + '.old'
if (Test-Path -LiteralPath $old) {{
    Move-Item -LiteralPath $old -Destination $target -Force -ErrorAction SilentlyContinue
    Write-Log 'restored'
}}
Start-Installed | Out-Null
if ($form -ne $null) {{ $form.Close() }}
exit 1
"""
    script.write_text(body, encoding="utf-8-sig")
    stale = install_directory() / "apply-update.bat"
    stale.unlink(missing_ok=True)
    helper = str(powershell) if powershell.is_file() else "powershell"
    _detached(
        [
            helper,
            "-NoProfile",
            "-STA",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(script),
        ],
        target.parent,
    )
    time.sleep(0.6)
