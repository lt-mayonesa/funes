"""Shared Funes modules.

Everything in this package is GTK-free on purpose: the store, the settings
wrapper, the capture filters and the X11 paster can be imported by a headless
process (tests, a future daemon) without pulling in a display connection.
"""

VERSION = "__PROJECT_VERSION__"

APP_ID = "org.x.funes"
APP_NAME = "Funes"
SETTINGS_SCHEMA = APP_ID
DESKTOP_ID = f"{APP_ID}.desktop"
GETTEXT_DOMAIN = "funes"
