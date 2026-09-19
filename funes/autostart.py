"""Launch at login via ~/.config/autostart."""

import shutil
from pathlib import Path

from gi.repository import GLib

from funes import DESKTOP_ID

_TEMPLATE = """[Desktop Entry]
Type=Application
Name=Funes
Comment=Clipboard history that never forgets
Exec={exec_path}
Icon=edit-paste
Terminal=false
Categories=Utility;GTK;
X-GNOME-Autostart-enabled=true
NoDisplay=true
"""


def _target() -> Path:
    return Path(GLib.get_user_config_dir()) / "autostart" / DESKTOP_ID


def _executable_path() -> str:
    """Prefer an installed `funes`; fall back to a plain command name so the
    entry also works when running from a source tree."""
    return shutil.which("funes") or "funes"


def enabled() -> bool:
    return _target().exists()


def set_enabled(enable: bool) -> None:
    path = _target()
    try:
        if not enable:
            path.unlink(missing_ok=True)
            return
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            handle.write(_TEMPLATE.format(exec_path=_executable_path()))
    except OSError as error:
        print(f"funes: cannot update autostart entry: {error}")
