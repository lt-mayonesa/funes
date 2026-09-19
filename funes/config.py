"""Thin wrapper over GSettings."""

from gi.repository import Gio

from funes import SETTINGS_SCHEMA


class Config:
    def __init__(self, schema=SETTINGS_SCHEMA):
        self.settings = Gio.Settings.new(schema)

    @property
    def history_size(self):
        return self.settings.get_int("history-size")

    @history_size.setter
    def history_size(self, value):
        self.settings.set_int("history-size", value)

    @property
    def hotkey(self):
        return self.settings.get_string("hotkey")

    @hotkey.setter
    def hotkey(self, value):
        self.settings.set_string("hotkey", value)

    @property
    def paste_on_select(self):
        return self.settings.get_boolean("paste-on-select")

    @paste_on_select.setter
    def paste_on_select(self, value):
        self.settings.set_boolean("paste-on-select", value)

    @property
    def launch_at_login(self):
        return self.settings.get_boolean("launch-at-login")

    @launch_at_login.setter
    def launch_at_login(self, value):
        self.settings.set_boolean("launch-at-login", value)

    @property
    def popup_width(self):
        return self.settings.get_int("popup-width")

    @popup_width.setter
    def popup_width(self, value):
        self.settings.set_int("popup-width", value)

    @property
    def popup_height(self):
        return self.settings.get_int("popup-height")

    @popup_height.setter
    def popup_height(self, value):
        self.settings.set_int("popup-height", value)

    @property
    def remember_size(self):
        return self.settings.get_boolean("remember-size")

    @remember_size.setter
    def remember_size(self, value):
        self.settings.set_boolean("remember-size", value)

    @property
    def max_item_bytes(self):
        return self.settings.get_int("max-item-bytes")

    @property
    def paste_ctrl_v_class_regex(self):
        return self.settings.get_string("paste-ctrl-v-class-regex")

    @paste_ctrl_v_class_regex.setter
    def paste_ctrl_v_class_regex(self, value):
        self.settings.set_string("paste-ctrl-v-class-regex", value)

    @property
    def paste_sets_primary(self):
        return self.settings.get_boolean("paste-sets-primary")

    @paste_sets_primary.setter
    def paste_sets_primary(self, value):
        self.settings.set_boolean("paste-sets-primary", value)

    @property
    def reown_clipboard(self):
        return self.settings.get_boolean("reown-clipboard")

    @reown_clipboard.setter
    def reown_clipboard(self, value):
        self.settings.set_boolean("reown-clipboard", value)

    @property
    def ignore_enabled(self):
        return self.settings.get_boolean("ignore-enabled")

    @ignore_enabled.setter
    def ignore_enabled(self, value):
        self.settings.set_boolean("ignore-enabled", value)

    @property
    def ignore_regexes(self):
        return list(self.settings.get_strv("ignore-regexes"))

    @ignore_regexes.setter
    def ignore_regexes(self, value):
        self.settings.set_strv("ignore-regexes", list(value))
