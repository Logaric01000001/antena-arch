"""Ventana principal y navegación."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from antena.constants import APP_ID  # noqa: E402
from antena.core.detect import DetectionResult, Detector  # noqa: E402
from antena.core.diagnose import Diagnostics  # noqa: E402
from antena.core.models import DeviceInfo, DeviceStatus  # noqa: E402
from antena.core.planner import build_repair_plan, build_setup_plan  # noqa: E402
from antena.core.privileged import PrivilegedClient  # noqa: E402
from antena.i18n import t  # noqa: E402
from antena.ui.pages import (  # noqa: E402
    AboutPage,
    DevicePage,
    DiagnosticsPage,
    HomePage,
    SettingsPage,
)
from antena.ui.repair import MonitorDialog, RepairPage, ScanDialog  # noqa: E402
from antena.ui.widgets import (  # noqa: E402
    app_icon_image,
    device_display_name,
    device_row,
    run_async,
    show_alert,
    status_text,
)


class AntenaWindow(Adw.ApplicationWindow):
    def __init__(self, app) -> None:
        super().__init__(application=app)
        self.app = app
        self.settings = app.settings
        self.detector = Detector()
        self.client = PrivilegedClient()
        self.detection: DetectionResult | None = None
        self._detecting = False
        self._current = ("home", None)
        self._suppress_nav = False
        self.set_title("Antena")
        self.set_default_size(1040, 700)
        self.set_size_request(760, 500)
        self.set_icon_name(APP_ID)
        self._register_icons()
        self._build()
        self._install_breakpoint()
        self.refresh()

    def _register_icons(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        from antena.ui.widgets import local_icon_path

        theme = Gtk.IconTheme.get_for_display(display)
        theme.add_search_path(str(local_icon_path()))

    # ------------------------------------------------------------------
    def _build(self) -> None:
        header = Adw.HeaderBar()
        self.header = header
        self.back_button = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text=t("action.back"))
        self.back_button.add_css_class("flat")
        self.back_button.set_visible(False)
        self.back_button.connect("clicked", lambda _b: self._go_back())
        header.pack_start(self.back_button)

        title = Adw.WindowTitle(title="Antena", subtitle=t("app.tagline"))
        self.window_title = title
        header.set_title_widget(title)

        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        header.pack_end(self.spinner)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=t("action.refresh"))
        refresh.add_css_class("flat")
        refresh.connect("clicked", lambda _b: self.refresh())
        header.pack_end(refresh)

        self.menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", visible=False)
        self.menu_button.set_tooltip_text(t("nav.home"))
        popover = Gtk.Popover()
        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        for key, icon, callback in (
            ("nav.home", "go-home-symbolic", self.show_home),
            ("nav.diagnostics", "utilities-system-monitor-symbolic", self.show_diagnostics),
            ("nav.settings", "emblem-system-symbolic", self.show_settings),
            ("nav.about", "help-about-symbolic", self.show_about),
        ):
            button = Gtk.Button(css_classes=["flat"])
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box.append(Gtk.Image.new_from_icon_name(icon))
            box.append(Gtk.Label(label=t(key), xalign=0))
            button.set_child(box)
            button.connect("clicked", lambda _b, cb=callback: (popover.popdown(), cb()))
            menu_box.append(button)
        popover.set_child(menu_box)
        self.menu_button.set_popover(popover)
        header.pack_end(self.menu_button)

        self.sidebar = self._build_sidebar()
        self.stack = Gtk.Stack()
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        body.append(self.sidebar)
        body.append(self.stack)
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(body)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self.toast_overlay)
        self.set_content(toolbar)

    def _build_sidebar(self) -> Gtk.Box:
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        sidebar.add_css_class("sidebar")
        sidebar.set_size_request(248, -1)
        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=11)
        brand.set_margin_top(18)
        brand.set_margin_bottom(10)
        brand.set_margin_start(18)
        brand.set_margin_end(16)
        brand.append(app_icon_image(40))
        brand_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, valign=Gtk.Align.CENTER)
        brand_text.append(Gtk.Label(label="ANTENA", xalign=0, css_classes=["brand-title"]))
        brand_text.append(Gtk.Label(label=t("app.tagline"), xalign=0, css_classes=["brand-sub"]))
        brand.append(brand_text)
        sidebar.append(brand)

        self.nav_list = Gtk.ListBox()
        self.nav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.nav_list.add_css_class("navigation-sidebar")
        self.nav_list.set_margin_start(8)
        self.nav_list.set_margin_end(8)
        self.nav_rows: dict[str, Gtk.ListBoxRow] = {}
        for key, icon in (
            ("home", "go-home-symbolic"),
            ("diagnostics", "utilities-system-monitor-symbolic"),
            ("settings", "emblem-system-symbolic"),
            ("about", "help-about-symbolic"),
        ):
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box.add_css_class("nav-row")
            icon_widget = Gtk.Image.new_from_icon_name(icon)
            label = Gtk.Label(label=t(f"nav.{key}"), xalign=0)
            box.append(icon_widget)
            box.append(label)
            row.set_child(box)
            self.nav_rows[key] = row
            self.nav_list.append(row)
        self.nav_list.connect("row-selected", self._nav_selected)
        sidebar.append(self.nav_list)

        divider = Gtk.Box(css_classes=["hairline"])
        divider.set_margin_start(18)
        divider.set_margin_end(18)
        divider.set_margin_top(2)
        sidebar.append(divider)

        heading = Gtk.Label(label=t("nav.adapters"), xalign=0, css_classes=["sidebar-section"])
        heading.set_margin_start(20)
        heading.set_margin_top(8)
        sidebar.append(heading)
        self.sidebar_devices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.sidebar_devices.set_margin_start(8)
        self.sidebar_devices.set_margin_end(8)
        sidebar.append(self.sidebar_devices)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        sidebar.append(spacer)
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        footer.set_margin_start(18)
        footer.set_margin_end(16)
        footer.set_margin_bottom(16)
        lock = Gtk.Image.new_from_icon_name("channel-secure-symbolic")
        lock.add_css_class("muted")
        text = Gtk.Label(label=t("app.privacy_short"), xalign=0, wrap=True, css_classes=["muted", "tiny"])
        footer.append(lock)
        footer.append(text)
        sidebar.append(footer)
        return sidebar

    def _install_breakpoint(self) -> None:
        try:
            condition = Adw.BreakpointCondition.parse("max-width: 840px")
            point = Adw.Breakpoint.new(condition)
            point.add_setter(self.sidebar, "visible", False)
            point.add_setter(self.menu_button, "visible", True)
            self.add_breakpoint(point)
        except Exception:
            # La ventana sigue siendo usable aunque esta versión de
            # libadwaita no exponga breakpoints.
            pass

    # ------------------------------------------------------------------
    def toast(self, message: str) -> None:
        toast = Adw.Toast(title=message)
        toast.set_timeout(4)
        self.toast_overlay.add_toast(toast)

    def _set_header(self, title: str, subtitle: str, back: bool) -> None:
        self.window_title.set_title(title)
        self.window_title.set_subtitle(subtitle)
        self.back_button.set_visible(back)

    def _set_page(self, page: Gtk.Widget) -> None:
        child = self.stack.get_first_child()
        while child is not None:
            self.stack.remove(child)
            child = self.stack.get_first_child()
        self.stack.add_child(page)

    def _select_nav(self, key: str | None) -> None:
        self._suppress_nav = True
        try:
            if key and key in self.nav_rows:
                self.nav_list.select_row(self.nav_rows[key])
            else:
                self.nav_list.unselect_all()
        finally:
            self._suppress_nav = False

    def _nav_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if self._suppress_nav or row is None:
            return
        for key, candidate in self.nav_rows.items():
            if candidate is row:
                {
                    "home": self.show_home,
                    "diagnostics": self.show_diagnostics,
                    "settings": self.show_settings,
                    "about": self.show_about,
                }[key]()
                break

    def _go_back(self) -> None:
        kind, device_id = self._current
        if kind == "repair" and device_id:
            self.show_device(device_id)
        else:
            self.show_home()

    # -- páginas --------------------------------------------------------
    def show_home(self) -> None:
        self._current = ("home", None)
        self._select_nav("home")
        self._set_header("Antena", t("app.tagline"), False)
        if self.detection is None:
            self._set_page(self._loading_page())
            return
        self._set_page(HomePage(self, self.detection))

    def _loading_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        spinner = Gtk.Spinner()
        spinner.start()
        box.append(spinner)
        box.append(Gtk.Label(label=t("state.loading"), css_classes=["page-sub"]))
        return box

    def show_device(self, device_id: str) -> None:
        device = self.detection.by_id(device_id) if self.detection else None
        if device is None:
            self.show_home()
            return
        self._current = ("device", device.id)
        self._select_nav(None)
        self._set_header(device_display_name(device), status_text(device.status), True)
        self._set_page(DevicePage(self, device))

    def show_repair(self, plan, device: DeviceInfo) -> None:
        self._current = ("repair", device.id)
        self._select_nav(None)
        title = t("wizard.repair.title") if plan.kind == "repair" else t("wizard.setup.title")
        self._set_header(title, device.name, True)
        self._set_page(RepairPage(self, plan, device))

    def show_diagnostics(self, device_id: str | None = None) -> None:
        if self.detection is None:
            return
        self._current = ("diagnostics", device_id)
        self._select_nav("diagnostics")
        self._set_header(t("diag.title"), "", False)
        self._set_page(DiagnosticsPage(self, device_id))

    def show_settings(self) -> None:
        self._current = ("settings", None)
        self._select_nav("settings")
        self._set_header(t("settings.title"), "", False)
        self._set_page(SettingsPage(self))

    def show_about(self) -> None:
        self._current = ("about", None)
        self._select_nav("about")
        self._set_header(t("about.title"), "", False)
        self._set_page(AboutPage(self))

    # -- acciones -------------------------------------------------------
    def device_primary_action(self, device_id: str) -> None:
        device = self.detection.by_id(device_id) if self.detection else None
        if device is None:
            return
        if device.status is DeviceStatus.READY:
            self.scan_device(device.id)
        elif device.status is DeviceStatus.UNSUPPORTED:
            self.show_diagnostics(device.id)
        elif device.status is DeviceStatus.NEEDS_SETUP:
            self._setup_device(device)
        else:
            self.repair_device(device.id)

    def _setup_device(self, device: DeviceInfo) -> None:
        if self.detection is None:
            return
        plan = build_setup_plan(device, self.detection.environment, self.detector.recipes)
        if not plan.stages:
            self.show_diagnostics(device.id)
            return
        self.show_repair(plan, device)

    def repair_device(self, device_id: str) -> None:
        device = self.detection.by_id(device_id) if self.detection else None
        if device is None:
            return
        self.spinner.set_visible(True)
        self.spinner.start()
        run_async(
            lambda: Diagnostics(self.detector, helper_available=self.client.available).run(device.id),
            lambda payload: self._repair_ready(device.id, payload),
            lambda exc: self._repair_error(exc),
        )

    def _repair_ready(self, device_id: str, payload) -> None:
        self.spinner.stop()
        self.spinner.set_visible(False)
        checks, detection = payload
        self.detection = detection
        device = detection.by_id(device_id)
        if device is None:
            self.toast(t("error.generic"))
            self.refresh()
            return
        plan = build_repair_plan(device, checks, self.detector.recipes)
        if not plan.stages:
            self.show_diagnostics(device.id)
            return
        self.show_repair(plan, device)

    def _repair_error(self, exc: Exception) -> None:
        self.spinner.stop()
        self.spinner.set_visible(False)
        show_alert(self, t("error.title"), f"{t('error.generic')}\n\n{exc}")

    def scan_device(self, device_id: str) -> None:
        device = self.detection.by_id(device_id) if self.detection else None
        if device is None or device.iface is None:
            show_alert(self, t("scan.failed"), t("device.no_interface"))
            return
        ScanDialog(self, device).present(self)

    def monitor_device(self, device_id: str) -> None:
        device = self.detection.by_id(device_id) if self.detection else None
        if device is None or device.iface is None:
            return
        if device.iface.connected:
            show_alert(self, t("monitor.title"), t("monitor.busy"))
            return
        if not self.client.available:
            show_alert(self, t("error.no_helper"), t("error.no_helper_body"))
            return
        MonitorDialog(self, device).present(self)

    # -- detección ------------------------------------------------------
    def refresh(self, keep_page: bool = True) -> None:
        if self._detecting:
            return
        self._detecting = True
        self.spinner.set_visible(True)
        self.spinner.start()
        run_async(self.detector.detect, lambda result: self._apply_detection(result, keep_page), self._detection_error)

    def _apply_detection(self, result: DetectionResult, keep_page: bool) -> None:
        self._detecting = False
        self.spinner.stop()
        self.spinner.set_visible(False)
        self.detection = result
        self._refresh_sidebar()
        if result.errors:
            self.toast(result.errors[0])
        kind, value = self._current
        if not keep_page:
            self.show_home()
        elif kind == "home":
            self.show_home()
        elif kind == "device" and value:
            device = result.by_id(value)
            if device is not None:
                self.show_device(value)
            else:
                self.show_home()
        # Diagnóstico y reparación no se reconstruyen solos para no perder
        # el estado de una comprobación o de una operación en curso.

    def _detection_error(self, exc: Exception) -> None:
        self._detecting = False
        self.spinner.stop()
        self.spinner.set_visible(False)
        self.toast(f"{t('error.detection')}: {exc}")
        if self.detection is None:
            self.show_home()

    def _refresh_sidebar(self) -> None:
        child = self.sidebar_devices.get_first_child()
        while child is not None:
            self.sidebar_devices.remove(child)
            child = self.sidebar_devices.get_first_child()
        devices = self.detection.devices if self.detection else []
        if not devices:
            label = Gtk.Label(label=t("home.title.empty"), xalign=0, wrap=True, css_classes=["muted", "tiny"])
            label.set_margin_start(12)
            label.set_margin_end(8)
            self.sidebar_devices.append(label)
            return
        for device in devices:
            self.sidebar_devices.append(device_row(device, self.show_device, compact=True))
