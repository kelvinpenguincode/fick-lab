"""Look up the newest FickLab.exe on GitHub and replace the running build."""

from __future__ import annotations

import json
import ssl
import sys
import tempfile
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
    return destination


def schedule_replacement(downloaded: Path) -> None:
    """Swap the running exe after this process exits. Windows locks the file until then."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Open FickLab.exe to install an update. The Python source is not replaced automatically.")
    target = Path(sys.executable).resolve()
    script = Path(tempfile.gettempdir()) / "ficklab_apply_update.bat"
    script.write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal",
                "set TRIES=0",
                ":retry",
                f'copy /Y "{downloaded}" "{target}" >nul',
                "if not errorlevel 1 goto launch",
                "set /a TRIES+=1",
                "if %TRIES% GEQ 20 goto failed",
                "ping 127.0.0.1 -n 2 >nul",
                "goto retry",
                ":launch",
                f'start "" "{target}"',
                'del "%~f0"',
                "exit /b 0",
                ":failed",
                f'echo FickLab could not replace "{target}".',
                "echo Close the app completely, then run this update again.",
                "pause",
                "exit /b 1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    import subprocess

    subprocess.Popen(
        ["cmd", "/c", str(script)],
        cwd=str(target.parent),
        close_fds=True,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
