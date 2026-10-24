"""Widgets y utilidades compartidas por las páginas GTK."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, TypeVar

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from antena.core.models import DeviceInfo, DeviceStatus  # noqa: E402
from antena.i18n import t  # noqa: E402

T = TypeVar("T")


def status_class(status: DeviceStatus) -> str:
    return {
        DeviceStatus.READY: "ready",
        DeviceStatus.NEEDS_SETUP: "setup",
        DeviceStatus.NEEDS_ATTENTION: "attention",
        DeviceStatus.UNSUPPORTED: "unsupported",
        DeviceStatus.BUSY: "setup",
    }.get(status, "unsupported")


def status_text(status: DeviceStatus) -> str:
    return t(f"state.{status.value}")


def status_dot(status: DeviceStatus) -> Gtk.Widget:
    dot = Gtk.Box(css_classes=["status-dot", f"dot-{status_class(status)}"])
    dot.set_valign(Gtk.Align.START)
    return dot


def status_pill(status: DeviceStatus) -> Gtk.Widget:
    label = Gtk.Label(label=status_text(status), css_classes=["status-pill", f"pill-{status_class(status)}"])
    label.set_halign(Gtk.Align.START)
    return label


def chip(text: str, kind: str = "") -> Gtk.Widget:
    classes = ["chip"]
    if kind:
        classes.append(f"chip-{kind}")
    label = Gtk.Label(label=text, css_classes=classes)
    label.set_halign(Gtk.Align.START)
    return label


def section_label(text: str) -> Gtk.Widget:
    label = Gtk.Label(label=text, css_classes=["section-title"], xalign=0)
    label.set_margin_top(10)
    label.set_margin_bottom(4)
    return label


def key_value(key: str, value: str, mono: bool = False, selectable: bool = True) -> Gtk.Widget:
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
    row.add_css_class("kv-row")
    name = Gtk.Label(label=key, xalign=0, css_classes=["muted", "tiny"])
    name.set_size_request(158, -1)
    name.set_valign(Gtk.Align.START)
    value_label = Gtk.Label(label=value or t("device.not_available"), xalign=0)
    value_label.set_wrap(True)
    value_label.set_selectable(selectable)
    value_label.set_hexpand(True)
    if mono:
        value_label.add_css_class("mono")
    row.append(name)
    row.append(value_label)
    return row


def hairline() -> Gtk.Widget:
    line = Gtk.Box(css_classes=["hairline"])
    line.set_margin_top(10)
    line.set_margin_bottom(10)
    return line


def icon_button(icon: str, tooltip: str, callback: Callable[[], None]) -> Gtk.Button:
    button = Gtk.Button(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
    button.add_css_class("flat")
    button.connect("clicked", lambda _button: callback())
    return button


def run_async(
    work: Callable[[], T],
    on_success: Callable[[T], None],
    on_error: Callable[[Exception], None] | None = None,
) -> None:
    def worker() -> None:
        try:
            value = work()
        except Exception as exc:  # se muestra al usuario, no se silencia
            if on_error is not None:
                GLib.idle_add(on_error, exc)
            return
        GLib.idle_add(on_success, value)

    threading.Thread(target=worker, daemon=True).start()


def show_alert(
    parent: Gtk.Widget,
    heading: str,
    body: str,
    confirm_label: str = "",
    on_confirm: Callable[[], None] | None = None,
    destructive: bool = False,
) -> Adw.AlertDialog:
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", t("action.cancel") if confirm_label else t("error.dismiss"))
    if confirm_label:
        dialog.add_response("confirm", confirm_label)
        dialog.set_response_appearance(
            "confirm",
            Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED,
        )

    def respond(_dialog: Adw.AlertDialog, response: str) -> None:
        if response == "confirm" and on_confirm is not None:
            on_confirm()

    dialog.connect("response", respond)
    dialog.present(parent)
    return dialog


def copy_to_clipboard(text: str) -> None:
    display = Gdk.Display.get_default()
    if display is not None:
        display.get_clipboard().set(text)


def device_display_name(device: DeviceInfo) -> str:
    """Nombre traducible: el nombre interno no se fija en el núcleo."""
    if device.internal and not device.recipe_id and device.iface is not None:
        return f"{t('home.internal')} · {device.iface.name}"
    return device.name


def device_row(device: DeviceInfo, on_click: Callable[[str], None], compact: bool = False) -> Gtk.Widget:
    if compact:
        button = Gtk.Button(css_classes=["flat", "device-row-compact"])
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        box.append(status_dot(device.status))
        label = Gtk.Label(label=device_display_name(device), xalign=0, ellipsize=3, hexpand=True)
        label.set_tooltip_text(device_display_name(device))
        box.append(label)
        button.set_child(box)
    else:
        button = Gtk.Button(css_classes=["flat", "device-row"])
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        box.append(status_dot(device.status))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        title = Gtk.Label(label=device_display_name(device), xalign=0)
        title.add_css_class("section-title")
        if device.internal:
            meta_parts = [status_text(device.status)]
        else:
            meta_parts = [
                device.usb_id.upper() if device.usb_id else t("home.internal"),
                status_text(device.status),
            ]
            if device.iface:
                meta_parts.append(device.iface.name)
        meta = Gtk.Label(label=" · ".join(meta_parts), xalign=0, css_classes=["muted", "tiny"])
        text.append(title)
        text.append(meta)
        box.append(text)
        arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
        arrow.add_css_class("muted")
        box.append(arrow)
        button.set_child(box)
    button.connect("clicked", lambda _button: on_click(device.id))
    return button


def device_action_key(device: DeviceInfo) -> str:
    if device.status is DeviceStatus.READY:
        return "action.test_scan"
    if device.status is DeviceStatus.UNSUPPORTED:
        return "action.diagnostics"
    if device.status is DeviceStatus.NEEDS_SETUP:
        return "action.configure"
    return "action.repair"


def format_bands(device: DeviceInfo) -> str:
    bands = {network for network in (device.iface.bands if device.iface else ())}
    if not bands:
        return t("band.unknown")
    return ", ".join(t(f"band.{band}") if band in {"2.4ghz", "5ghz", "6ghz"} else band for band in bands)


def local_icon_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "icons"


def app_icon_image(size: int = 40) -> Gtk.Widget:
    image = Gtk.Image.new_from_icon_name("io.github.antena.Antena")
    image.set_pixel_size(size)
    return image
