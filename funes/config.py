"""Thin wrapper over GSettings."""

from collections.abc import Iterable

from gi.repository import Gio

from funes import SETTINGS_SCHEMA
from funes.monitors import normalize_order


class Config:
    def __init__(self, schema: str = SETTINGS_SCHEMA) -> None:
        self.settings = Gio.Settings.new(schema)

    @property
    def history_size(self) -> int:
        return self.settings.get_int("history-size")

    @history_size.setter
    def history_size(self, value: int) -> None:
        self.settings.set_int("history-size", value)

    @property
    def hotkey(self) -> str:
        return self.settings.get_string("hotkey")

    @hotkey.setter
    def hotkey(self, value: str) -> None:
        self.settings.set_string("hotkey", value)

    @property
    def paste_on_select(self) -> bool:
        return self.settings.get_boolean("paste-on-select")

    @paste_on_select.setter
    def paste_on_select(self, value: bool) -> None:
        self.settings.set_boolean("paste-on-select", value)

    @property
    def popup_single_click_activates(self) -> bool:
        return self.settings.get_boolean("popup-single-click-activates")

    @popup_single_click_activates.setter
    def popup_single_click_activates(self, value: bool) -> None:
        self.settings.set_boolean("popup-single-click-activates", value)

    @property
    def launch_at_login(self) -> bool:
        return self.settings.get_boolean("launch-at-login")

    @launch_at_login.setter
    def launch_at_login(self, value: bool) -> None:
        self.settings.set_boolean("launch-at-login", value)

    @property
    def popup_width(self) -> int:
        return self.settings.get_int("popup-width")

    @popup_width.setter
    def popup_width(self, value: int) -> None:
        self.settings.set_int("popup-width", value)

    @property
    def popup_height(self) -> int:
        return self.settings.get_int("popup-height")

    @popup_height.setter
    def popup_height(self, value: int) -> None:
        self.settings.set_int("popup-height", value)

    @property
    def popup_monitor_order(self) -> list[str]:
        return normalize_order(self.settings.get_strv("popup-monitor-order"))

    @popup_monitor_order.setter
    def popup_monitor_order(self, value: Iterable[str]) -> None:
        self.settings.set_strv("popup-monitor-order", normalize_order(value))

    @property
    def remember_size(self) -> bool:
        return self.settings.get_boolean("remember-size")

    @remember_size.setter
    def remember_size(self, value: bool) -> None:
        self.settings.set_boolean("remember-size", value)

    @property
    def max_item_bytes(self) -> int:
        return self.settings.get_int("max-item-bytes")

    @property
    def paste_ctrl_v_class_regex(self) -> str:
        return self.settings.get_string("paste-ctrl-v-class-regex")

    @paste_ctrl_v_class_regex.setter
    def paste_ctrl_v_class_regex(self, value: str) -> None:
        self.settings.set_string("paste-ctrl-v-class-regex", value)

    @property
    def paste_primary_class_regex(self) -> str:
        return self.settings.get_string("paste-primary-class-regex")

    @paste_primary_class_regex.setter
    def paste_primary_class_regex(self, value: str) -> None:
        self.settings.set_string("paste-primary-class-regex", value)

    @property
    def reown_clipboard(self) -> bool:
        return self.settings.get_boolean("reown-clipboard")

    @reown_clipboard.setter
    def reown_clipboard(self, value: bool) -> None:
        self.settings.set_boolean("reown-clipboard", value)

    @property
    def ignore_enabled(self) -> bool:
        return self.settings.get_boolean("ignore-enabled")

    @ignore_enabled.setter
    def ignore_enabled(self, value: bool) -> None:
        self.settings.set_boolean("ignore-enabled", value)

    @property
    def ignore_regexes(self) -> list[str]:
        return list(self.settings.get_strv("ignore-regexes"))

    @ignore_regexes.setter
    def ignore_regexes(self, value: Iterable[str]) -> None:
        self.settings.set_strv("ignore-regexes", list(value))

    @property
    def capture_images(self) -> bool:
        return self.settings.get_boolean("capture-images")

    @capture_images.setter
    def capture_images(self, value: bool) -> None:
        self.settings.set_boolean("capture-images", value)

    @property
    def max_image_bytes(self) -> int:
        return self.settings.get_int("max-image-bytes")

    @max_image_bytes.setter
    def max_image_bytes(self, value: int) -> None:
        self.settings.set_int("max-image-bytes", value)

    @property
    def image_row_height(self) -> int:
        return self.settings.get_int("image-row-height")

    @image_row_height.setter
    def image_row_height(self, value: int) -> None:
        self.settings.set_int("image-row-height", value)

    @property
    def ocr_enabled(self) -> bool:
        return self.settings.get_boolean("ocr-enabled")

    @ocr_enabled.setter
    def ocr_enabled(self, value: bool) -> None:
        self.settings.set_boolean("ocr-enabled", value)
