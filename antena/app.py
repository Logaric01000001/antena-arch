"""Aplicación GTK4 + libadwaita."""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from antena.constants import APP_ID  # noqa: E402
from antena.i18n import set_language  # noqa: E402
from antena.settings import load_settings  # noqa: E402


class AntenaApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.settings = load_settings()
        set_language(self.settings.effective_language)

    def do_startup(self) -> None:  # noqa: N802
        Adw.Application.do_startup(self)
        self._load_css()
        self.apply_appearance()

    def _load_css(self) -> None:
        provider = Gtk.CssProvider()
        css_path = Path(__file__).resolve().parent / "ui" / "style.css"
        try:
            provider.load_from_path(str(css_path))
        except Exception:
            return
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def apply_appearance(self) -> None:
        manager = Adw.StyleManager.get_default()
        scheme = {
            "light": Adw.ColorScheme.FORCE_LIGHT,
            "dark": Adw.ColorScheme.FORCE_DARK,
        }.get(self.settings.appearance, Adw.ColorScheme.DEFAULT)
        manager.set_color_scheme(scheme)

    def do_activate(self) -> None:  # noqa: N802
        window = self.props.active_window
        if window is None:
            from antena.ui.window import AntenaWindow

            window = AntenaWindow(self)
        window.present()

    def reload_ui(self) -> None:
        """Reconstruye la ventana para aplicar idioma o preferencias."""
        old = self.props.active_window
        self.settings = load_settings()
        set_language(self.settings.effective_language)
        from antena.ui.window import AntenaWindow

        new_window = AntenaWindow(self)
        new_window.present()
        if old is not None and old is not new_window:
            old.destroy()


def main() -> int:
    app = AntenaApplication()
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    raise SystemExit(main())
