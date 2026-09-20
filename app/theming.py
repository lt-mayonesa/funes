"""Funes' own layout, density and typography on top of the system theme.

Colors are never hardcoded: everything resolves to GTK theme colors so the
popup follows the desktop's light/dark and accent choices. What Funes owns is
spacing, rhythm and the keycap language.
"""

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk

CSS = b"""
.funes-popup {
  border: 1px solid @borders;
}

/* ---------------------------------------------------------- search row */
.funes-search {
  padding: 8px 12px;
  border-bottom: 1px solid @borders;
}
.funes-search entry {
  background: none;
  border: none;
  box-shadow: none;
  padding: 0;
  min-height: 0;
  caret-color: @theme_selected_bg_color;
}
.funes-search-icon {
  color: alpha(@theme_fg_color, 0.55);
}
.funes-count {
  color: alpha(@theme_fg_color, 0.55);
  font-size: 12px;
  font-feature-settings: "tnum";
}

/* --------------------------------------------------------------- rows */
.funes-list {
  background: none;
  padding: 4px;
}
.funes-list row {
  padding: 0;
  min-height: 28px;
  border-radius: 6px;
}
.funes-row {
  padding: 3px 8px;
}
.funes-num {
  font-family: monospace;
  font-size: 11px;
  color: alpha(@theme_fg_color, 0.55);
  border: 1px solid alpha(@theme_fg_color, 0.22);
  border-radius: 4px;
  padding: 1px 4px;
  min-width: 18px;
  min-height: 0;
}
.funes-list row:selected .funes-num {
  color: @theme_selected_fg_color;
  background: alpha(@theme_selected_fg_color, 0.22);
  border-color: transparent;
}
.funes-mono {
  font-family: monospace;
  font-size: 12.5px;
}
.funes-age {
  font-size: 12px;
  color: alpha(@theme_fg_color, 0.55);
  font-feature-settings: "tnum";
}
.funes-num-placeholder {
  font-family: monospace;
  font-size: 11px;
  padding: 1px 4px;
  min-width: 18px;
  min-height: 0;
}
.funes-list row:selected .funes-age,
.funes-list row:selected .funes-num-placeholder {
  color: alpha(@theme_selected_fg_color, 0.82);
}
.funes-swatch {
  border: 1px solid alpha(@theme_fg_color, 0.4);
  border-radius: 3px;
}

/* ------------------------------------------------------ empty / footer */
.funes-empty {
  padding: 36px 18px;
  color: alpha(@theme_fg_color, 0.55);
}
.funes-empty-title {
  font-weight: bold;
  color: @theme_fg_color;
}
.funes-footer {
  padding: 6px 11px;
  border-top: 1px solid @borders;
  background: alpha(@theme_fg_color, 0.04);
  font-size: 12px;
  color: alpha(@theme_fg_color, 0.55);
}
/* ------------------------------------------------- preferences widgets */
.funes-monitor-order {
  background: none;
}
.funes-key {
  font-family: monospace;
  font-size: 11px;
  color: @theme_fg_color;
  background: alpha(@theme_fg_color, 0.1);
  border: 1px solid alpha(@theme_fg_color, 0.2);
  border-bottom: 2px solid alpha(@theme_fg_color, 0.2);
  border-radius: 5px;
  padding: 0 5px;
}
"""


def load_styles() -> None:
    """Install the Funes stylesheet once, at application level."""
    screen = Gdk.Screen.get_default()
    if screen is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
