"""Launch at login via ~/.config/autostart."""

import os
import shutil

from gi.repository import GLib

from funes import DESKTOP_ID

_TEMPLATE = """[Desktop Entry]
Type=Application
Name=Funes
Comment=Clipboard history that never forgets
Exec=%s
Icon=edit-paste
Terminal=false
Categories=Utility;GTK;
X-GNOME-Autostart-enabled=true
NoDisplay=true
"""


def _target():
    return os.path.join(GLib.get_user_config_dir(), "autostart", DESKTOP_ID)


def _executable_path():
    """Prefer an installed `funes`; fall back to a plain command name so the
    entry also works when running from a source tree."""
    return shutil.which("funes") or "funes"


def enabled():
    return os.path.exists(_target())


def set_enabled(enable):
    path = _target()
    try:
        if not enable:
            if os.path.exists(path):
                os.remove(path)
            return
        if os.path.exists(path):
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(_TEMPLATE % _executable_path())
    except OSError as error:
        print("funes: cannot update autostart entry: %s" % error)
