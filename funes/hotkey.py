"""Global shortcut registration.

Instead of grabbing the key in-process (libkeybinder / XGrabKey), Funes
registers a Cinnamon custom keybinding that runs `funes toggle`. Benefits: no
extra runtime dependency, the shortcut is visible and editable in Keyboard
Settings, and it also works when Funes is not running (the launcher starts it).
"""

from collections.abc import Iterable

from gi.repository import Gio

from funes import accel as accel_mod

KB_SCHEMA = "org.cinnamon.desktop.keybindings"
CUSTOM_SCHEMA = "org.cinnamon.desktop.keybindings.custom-keybinding"
CUSTOM_PATH_PREFIX = "/org/cinnamon/desktop/keybindings/custom-keybindings/"
COMMAND = "funes toggle"
NAME = "Funes clipboard history"


def cinnamon_available() -> bool:
    source = Gio.SettingsSchemaSource.get_default()
    return source is not None and source.lookup(KB_SCHEMA, True) is not None


def apply(accel: str) -> bool:
    """Register `accel`, or unregister the binding when it is blank/invalid.

    Single entry point for both startup and live GSettings changes, so a
    cleared shortcut actually removes the Cinnamon keybinding instead of
    leaving the previous one grabbed.
    """
    wanted = accel_mod.normalize(accel)
    if not accel_mod.is_valid(wanted):
        unregister()
        return False
    return ensure(wanted)


def ensure(accel: str) -> bool:
    """Make sure a Cinnamon custom keybinding exists for accel.

    Returns True when the binding is in place.
    """
    if not cinnamon_available():
        print(
            f"funes: Cinnamon keybinding schema not found; bind '{accel}' to '{COMMAND}' manually"
        )
        return False

    keybindings = Gio.Settings.new(KB_SCHEMA)
    entries = list(keybindings.get_strv("custom-list"))

    slot_id = _find_slot(entries) or _next_free_id(entries)
    _apply(_custom_settings(slot_id), accel)

    # Cinnamon stores either bare ids ("custom0") or full paths; bare ids are
    # what cinnamon-settings writes.
    updated = [entry for entry in entries if _basename(entry) != slot_id]
    updated.append(slot_id)

    # Cinnamon rebuilds its grabs from `custom-list`. Editing only the slot's
    # `binding` key left the old accelerator grabbed until the next login, so
    # drop the entry and re-add it to force a re-read.
    if [_basename(entry) for entry in entries] == [_basename(entry) for entry in updated]:
        keybindings.set_strv("custom-list", [e for e in updated if _basename(e) != slot_id])
        Gio.Settings.sync()
    keybindings.set_strv("custom-list", updated)
    Gio.Settings.sync()
    print(f"funes: registered '{accel}' -> '{COMMAND}' ({slot_id})")
    return True


def unregister() -> None:
    """Remove the Funes custom keybinding."""
    if not cinnamon_available():
        return
    keybindings = Gio.Settings.new(KB_SCHEMA)
    kept: list[str] = []
    for entry in keybindings.get_strv("custom-list"):
        slot_id = _basename(entry)
        if not slot_id:
            continue
        if slot_id != "__dummy__":
            slot = _custom_settings(slot_id)
            if slot.get_string("command") == COMMAND:
                slot.reset("binding")
                slot.reset("command")
                slot.reset("name")
                continue
        kept.append(entry)
    keybindings.set_strv("custom-list", kept)
    Gio.Settings.sync()


def _find_slot(entries: Iterable[str]) -> str | None:
    """Id of the existing Funes slot, if any."""
    for entry in entries:
        slot_id = _basename(entry)
        if slot_id in ("", "__dummy__"):
            continue
        if _custom_settings(slot_id).get_string("command") == COMMAND:
            return slot_id
    return None


def _apply(slot: Gio.Settings, accel: str) -> None:
    slot.set_string("name", NAME)
    slot.set_string("command", COMMAND)
    slot.set_strv("binding", [accel])


def _custom_settings(slot_id: str) -> Gio.Settings:
    return Gio.Settings.new_with_path(CUSTOM_SCHEMA, CUSTOM_PATH_PREFIX + slot_id + "/")


def _basename(entry: str) -> str:
    trimmed = entry.rstrip("/")
    return trimmed.rsplit("/", 1)[-1] if "/" in trimmed else trimmed


def _next_free_id(entries: Iterable[str]) -> str:
    taken = {_basename(entry) for entry in entries}
    for index in range(100):
        candidate = f"custom{index:d}"
        if candidate not in taken:
            return candidate
    return "funes0"
