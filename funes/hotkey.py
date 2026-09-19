"""Global shortcut registration.

Instead of grabbing the key in-process (libkeybinder / XGrabKey), Funes
registers a Cinnamon custom keybinding that runs `funes toggle`. Benefits: no
extra runtime dependency, the shortcut is visible and editable in Keyboard
Settings, and it also works when Funes is not running (the launcher starts it).
"""

from gi.repository import Gio

KB_SCHEMA = "org.cinnamon.desktop.keybindings"
CUSTOM_SCHEMA = "org.cinnamon.desktop.keybindings.custom-keybinding"
CUSTOM_PATH_PREFIX = "/org/cinnamon/desktop/keybindings/custom-keybindings/"
COMMAND = "funes toggle"
NAME = "Funes clipboard history"


def cinnamon_available():
    source = Gio.SettingsSchemaSource.get_default()
    return source is not None and source.lookup(KB_SCHEMA, True) is not None


def ensure(accel):
    """Make sure a Cinnamon custom keybinding exists for accel.

    Returns True when the binding is in place.
    """
    if not cinnamon_available():
        print(
            "funes: Cinnamon keybinding schema not found; bind '%s' to '%s' "
            "manually" % (accel, COMMAND)
        )
        return False

    keybindings = Gio.Settings.new(KB_SCHEMA)
    entries = list(keybindings.get_strv("custom-list"))

    # Reuse our own entry if it already exists.
    for entry in entries:
        slot_id = _basename(entry)
        if slot_id in ("", "__dummy__"):
            continue
        slot = _custom_settings(slot_id)
        if slot.get_string("command") == COMMAND:
            _apply(slot, accel)
            return True

    slot_id = _next_free_id(entries)
    _apply(_custom_settings(slot_id), accel)

    # Cinnamon stores either bare ids ("custom0") or full paths; bare ids are
    # what cinnamon-settings writes.
    updated = [entry for entry in entries if _basename(entry) != slot_id]
    updated.append(slot_id)
    keybindings.set_strv("custom-list", updated)
    Gio.Settings.sync()
    print("funes: registered '%s' -> '%s' (%s)" % (accel, COMMAND, slot_id))
    return True


def unregister():
    """Remove the Funes custom keybinding."""
    if not cinnamon_available():
        return
    keybindings = Gio.Settings.new(KB_SCHEMA)
    kept = []
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


def _apply(slot, accel):
    slot.set_string("name", NAME)
    slot.set_string("command", COMMAND)
    slot.set_strv("binding", [accel])


def _custom_settings(slot_id):
    return Gio.Settings.new_with_path(CUSTOM_SCHEMA, CUSTOM_PATH_PREFIX + slot_id + "/")


def _basename(entry):
    trimmed = entry.rstrip("/")
    return trimmed.rsplit("/", 1)[-1] if "/" in trimmed else trimmed


def _next_free_id(entries):
    taken = {_basename(entry) for entry in entries}
    for index in range(100):
        candidate = "custom%d" % index
        if candidate not in taken:
            return candidate
    return "funes0"
