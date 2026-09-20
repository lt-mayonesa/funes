#!/usr/bin/python3
"""Funes - clipboard history that never forgets.

Single-instance Gtk.Application: `funes toggle` from the global shortcut is
delivered to the running instance over DBus (and starts one if needed).
"""

import os
import shutil
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk
from setproctitle import setproctitle
from xapp.util import l10n

from funes import APP_ID, APP_NAME, GETTEXT_DOMAIN, VERSION

# The version is substituted at install time; running from a source tree leaves
# the placeholder behind.
if VERSION.startswith("__"):
    VERSION = "dev"
from funes import autostart, hotkey, log
from funes.config import Config
from funes.item import HistoryItem
from funes.ocr import OCRWorker
from funes.ocr import available as ocr_available
from funes.paster import Paster
from funes.store import HistoryStore
from theming import load_styles

from clipboard import ClipboardMonitor
from popup import PopupWindow
from preferences import PreferencesWindow
from tray import Tray

_ = l10n(GETTEXT_DOMAIN)

USAGE = """Funes %s — clipboard history that never forgets

usage:
  funes              start the tray daemon
  funes toggle       show/hide the history popup
  funes show         show the history popup
  funes clear        clear history (pinned items are kept)
  funes settings     open the settings dialog
  funes quit         stop the running instance
  funes --version    print version
"""


class FunesApplication(Gtk.Application):
    # Built in do_startup(), which GApplication always runs before any of the
    # command-line verbs below.
    _config: Config
    _store: HistoryStore
    _monitor: ClipboardMonitor
    _paster: Paster
    _tray: Tray
    _ocr_worker: OCRWorker | None

    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self._popup: PopupWindow | None = None
        self._preferences: PreferencesWindow | None = None
        self._started = False
        self._ocr_worker: OCRWorker | None = None

    # --- lifecycle ---

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        if self._started:
            return

        log.configure()
        load_styles()
        self._config = Config()
        self._store = HistoryStore(history_size=self._config.history_size)
        self._config.settings.connect(
            "changed::history-size",
            self._on_history_size_changed,
        )

        self._paster = Paster()
        self._monitor = ClipboardMonitor(self._config)
        self._monitor.connect("captured", self._on_captured)

        # Start OCR worker if tesseract is available.
        if ocr_available():
            self._ocr_worker = OCRWorker()
            self._ocr_worker.start()
        else:
            self._ocr_worker = None
            self._maybe_nudge_install_tesseract()

        self._tray = Tray()
        self._tray.connect("open-requested", lambda *_a: self._show_popup())
        self._tray.connect("settings-requested", lambda *_a: self._show_settings())
        self._tray.connect("clear-requested", lambda *_a: self._clear_history())
        self._tray.connect("quit-requested", lambda *_a: self._quit())
        self._tray.set_count(self._store.size())

        self._monitor.start()

        if self._config.launch_at_login and not autostart.enabled():
            autostart.set_enabled(True)
        hotkey.ensure(self._config.hotkey)

        # Tray-only app: keep running with no window open.
        self.hold()
        self._started = True

    def _maybe_nudge_install_tesseract(self) -> None:
        """Fire a one-time notification and start a watcher when tesseract is missing.

        The watcher polls every 5 s; when tesseract appears (e.g. after the user
        installs it from the Software Manager) it restarts Funes automatically so
        OCR becomes active without manual intervention.
        """
        # Always watch — restart as soon as tesseract shows up.
        self._start_tesseract_watcher()

        # Notification fires only once.
        if self._config.settings.get_boolean("ocr-nudge-shown"):
            return
        self._config.settings.set_boolean("ocr-nudge-shown", True)

        # Register the install action before sending the notification.
        install_action = Gio.SimpleAction.new("install-tesseract", None)
        install_action.connect(
            "activate",
            lambda *_: Gio.AppInfo.launch_default_for_uri("apt://tesseract-ocr", None),
        )
        self.add_action(install_action)

        notif = Gio.Notification.new(_("Enable image text search"))
        notif.set_body(
            _("Install tesseract-ocr to let Funes extract and search text inside clipboard images.")
        )
        notif.add_button(_("Install"), "app.install-tesseract")
        notif.set_default_action("app.install-tesseract")
        GLib.idle_add(self.send_notification, "ocr-nudge", notif)

    def _start_tesseract_watcher(self) -> None:
        """Daemon thread that restarts Funes the moment tesseract becomes available."""
        stop = threading.Event()

        def _watch() -> None:
            while not stop.wait(timeout=5):
                if shutil.which("tesseract") is not None:
                    GLib.idle_add(self._restart_for_ocr)
                    return

        t = threading.Thread(target=_watch, daemon=True, name="tesseract-watcher")
        t.start()

    def _restart_for_ocr(self) -> bool:
        """Replace the running process with a fresh Funes instance."""
        exe = shutil.which(sys.argv[0]) or sys.argv[0]
        os.execv(exe, sys.argv)
        return False  # unreachable; satisfies GLib idle signature

    def _on_history_size_changed(self, settings: Gio.Settings, _key: str) -> None:
        self._store.history_size = settings.get_int("history-size")

    def do_activate(self) -> None:
        # Plain `funes` just starts the daemon; nothing to show.
        pass

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        args = command_line.get_arguments()
        verb = args[1] if len(args) > 1 else ""

        if verb == "":
            self.activate()
        elif verb == "toggle":
            self._toggle_popup()
        elif verb == "show":
            self._show_popup()
        elif verb == "clear":
            self._clear_history()
        elif verb == "settings":
            self._show_settings()
        elif verb == "quit":
            self._quit()
        else:
            command_line.printerr_literal(f"funes: unknown command '{verb}'\n")
            command_line.printerr_literal(
                "usage: funes [toggle|show|clear|settings|quit|--version]\n"
            )
            return 2
        return 0

    def do_shutdown(self) -> None:
        if self._ocr_worker is not None:
            self._ocr_worker.stop()
        if self._started:
            self._store.flush()
        Gtk.Application.do_shutdown(self)

    # --- actions ---

    def _ensure_popup(self) -> PopupWindow:
        if self._popup is None:
            self._popup = PopupWindow(self._store, self._config)
            self._popup.connect("item-chosen", self._on_item_chosen)
            self._config.settings.connect(
                "changed::image-row-height",
                lambda _s, _k: self._popup.reload() if self._popup else None,
            )
            self.add_window(self._popup)
        return self._popup

    def _show_popup(self) -> None:
        window = self._ensure_popup()
        # Must happen before the popup takes focus, otherwise the paste target
        # would be Funes itself.
        if not window.get_visible():
            self._paster.remember_target()
        window.show_popup()

    def _toggle_popup(self) -> None:
        window = self._ensure_popup()
        if window.get_visible():
            window.hide_popup()
        else:
            self._show_popup()

    def _clear_history(self) -> None:
        self._store.clear()
        self._tray.set_count(self._store.size())
        self._store.flush()

    def _show_settings(self) -> None:
        if self._preferences is not None:
            self._preferences.present()
            return
        self._preferences = PreferencesWindow(self._config)
        self._preferences.connect("destroy", self._on_preferences_destroyed)
        self.add_window(self._preferences)
        self._preferences.present()

    def _quit(self) -> None:
        self._store.flush()
        self.quit()

    # --- signal handlers ---

    def _on_captured(self, _monitor: ClipboardMonitor, capture: object) -> None:
        from funes.item import Capture as _Capture

        assert isinstance(capture, _Capture)
        item = self._store.add(capture)
        self._tray.set_count(self._store.size())
        if item is not None and item.kind == "image":
            # Probe dimensions in a worker thread to keep the UI responsive.
            import threading

            import gi

            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf

            blob_store = self._store.blob_store
            store = self._store

            def _probe() -> None:
                if item.blob_sha is None:
                    return
                try:
                    data = blob_store.read(item.blob_sha)
                    loader = GdkPixbuf.PixbufLoader.new()
                    loader.write(data)
                    loader.close()
                    pixbuf = loader.get_pixbuf()
                    if pixbuf is not None:
                        w, h = pixbuf.get_width(), pixbuf.get_height()
                        GLib.idle_add(store.set_image_dimensions, item, w, h)
                except Exception as exc:
                    from funes import log

                    log.debug(f"dimension probe failed: {exc}")

            threading.Thread(target=_probe, daemon=True).start()

            # Enqueue OCR after dimensions are set (a separate worker so
            # the dimension probe and OCR don't race).
            if (
                self._ocr_worker is not None
                and self._config.ocr_enabled
                and item.blob_sha is not None
            ):
                import tempfile as _tempfile

                blob_sha = item.blob_sha
                _blob_store = self._store.blob_store
                _store = self._store
                _item = item

                def _run_ocr() -> None:
                    tmp_path: Path | None = None
                    try:
                        data = _blob_store.read(blob_sha)
                        # Correct extension so Tesseract picks the right codec.
                        ext = "." + (_item.mime or "image/png").split("/")[-1].lower()
                        with _tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                            tmp.write(data)
                            tmp_path = Path(tmp.name)

                        def _on_ocr_result(text: str) -> None:
                            _store.set_ocr_text(_item, text)
                            if tmp_path is not None:
                                tmp_path.unlink(missing_ok=True)

                        if self._ocr_worker is not None:
                            self._ocr_worker.enqueue(tmp_path, _on_ocr_result)
                        else:
                            tmp_path.unlink(missing_ok=True)
                    except Exception as exc:
                        log.debug(f"OCR enqueue failed: {exc}")
                        if tmp_path is not None:
                            tmp_path.unlink(missing_ok=True)

                threading.Thread(target=_run_ocr, daemon=True).start()

    def _on_item_chosen(self, _popup: PopupWindow, item: HistoryItem, paste: bool) -> None:
        # Inject blob_store reference so set_item can serve blobs.
        self._monitor._blob_store = self._store.blob_store  # type: ignore[attr-defined]
        if item.kind == "text":
            self._monitor.set_text(item.text or "", paste and self._config.paste_sets_primary)
        else:
            self._monitor.set_item(item)
        self._store.touch(item)
        if paste:
            self._paster.paste(self._config.paste_ctrl_v_class_regex)

    def _on_preferences_destroyed(self, *_args: object) -> None:
        self._preferences = None


def main(argv: list[str]) -> int:
    # Handled locally so they work without DBus round-trips.
    for arg in argv:
        if arg in ("--version", "-V"):
            print(f"funes {VERSION}")
            return 0
        if arg in ("--help", "-h"):
            print(USAGE % VERSION)
            return 0

    setproctitle("funes")
    GLib.set_application_name(APP_NAME)
    GLib.set_prgname("funes")
    # Without this the WM_CLASS of our windows would be derived from the
    # script name ("Funes_app.py").
    Gdk.set_program_class(APP_NAME)
    return FunesApplication().run(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
