"""Páginas principales de Antena (Inicio, Mi antena, Diagnóstico, Ajustes, Acerca de)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from antena.constants import LICENSE_NAME, PROJECT_URL, VERSION  # noqa: E402
from antena.core.catalog import find_recipe  # noqa: E402
from antena.core.diagnose import Diagnostics  # noqa: E402
from antena.core.models import (  # noqa: E402
    CheckResult,
    DeviceInfo,
    DeviceStatus,
    UsbStage,
)
from antena.core.planner import build_repair_plan  # noqa: E402
from antena.core.report import build_report, save_report  # noqa: E402
from antena.i18n import t  # noqa: E402
from antena.ui.widgets import (  # noqa: E402
    app_icon_image,
    chip,
    copy_to_clipboard,
    device_action_key,
    device_display_name,
    device_row,
    format_bands,
    hairline,
    key_value,
    run_async,
    section_label,
    status_pill,
)


def _page_box() -> Gtk.Box:
    return Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=14,
        margin_top=30,
        margin_bottom=34,
        margin_start=38,
        margin_end=38,
    )


class HomePage(Gtk.ScrolledWindow):
    def __init__(self, window, detection) -> None:
        super().__init__()
        self.window = window
        self.detection = detection
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_hexpand(True)
        self.set_vexpand(True)
        content = _page_box()
        clamp = Adw.Clamp(maximum_size=820, tightening_threshold=620)
        clamp.set_child(content)
        self.set_child(clamp)

        devices = detection.devices
        needs_action = next(
            (item for item in devices if item.status is DeviceStatus.NEEDS_SETUP),
            None,
        )
        attention = next(
            (item for item in devices if item.status is DeviceStatus.NEEDS_ATTENTION),
            None,
        )
        primary = needs_action or attention

        if not devices:
            title_key = "home.title.empty"
            subtitle_key = "home.subtitle.empty"
        elif needs_action is not None:
            title_key = "home.title.found"
            subtitle_key = "home.subtitle.found"
        elif attention is not None:
            title_key = "home.title.attention"
            subtitle_key = "home.subtitle.attention"
        else:
            title_key = "home.title.ready"
            subtitle_key = "home.subtitle.ready"

        eyebrow = Gtk.Label(label=t("nav.home").upper(), xalign=0, css_classes=["eyebrow"])
        title = Gtk.Label(label=t(title_key), xalign=0, css_classes=["display"])
        title.set_wrap(True)
        subtitle = Gtk.Label(label=t(subtitle_key), xalign=0, css_classes=["page-sub"])
        subtitle.set_wrap(True)
        subtitle.set_max_width_chars(64)
        content.append(eyebrow)
        content.append(title)
        content.append(subtitle)

        if primary is not None:
            label = t(device_action_key(primary))
            action = Gtk.Button(label=label, halign=Gtk.Align.START)
            action.add_css_class("suggested-action")
            action.set_margin_top(4)
            action.connect("clicked", lambda _b: self.window.device_primary_action(primary.id))
            content.append(action)
        elif devices:
            ready_usb = next(
                (item for item in devices if item.kind == "usb" and item.status is DeviceStatus.READY),
                None,
            )
            if ready_usb is not None:
                action = Gtk.Button(label=t("action.test_scan"), halign=Gtk.Align.START)
                action.add_css_class("suggested-action")
                action.connect("clicked", lambda _b: self.window.scan_device(ready_usb.id))
                content.append(action)

        if not devices:
            art = Gtk.Image.new_from_icon_name("io.github.antena.Antena")
            art.set_pixel_size(88)
            art.set_halign(Gtk.Align.START)
            art.set_margin_top(14)
            art.set_margin_bottom(4)
            content.append(art)
            body = Gtk.Label(label=t("home.empty.body"), xalign=0, css_classes=["page-sub"])
            body.set_wrap(True)
            hint = Gtk.Label(label=t("home.empty.hint"), xalign=0, css_classes=["muted", "tiny"])
            hint.set_wrap(True)
            content.append(body)
            content.append(hint)

        if devices:
            content.append(hairline())
            content.append(Gtk.Label(label=t("home.adapters"), xalign=0, css_classes=["section-title"]))
            listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            for index, device in enumerate(devices):
                listing.append(device_row(device, self.window.show_device))
                if index < len(devices) - 1:
                    listing.append(hairline())
            content.append(listing)

        content.append(hairline())
        privacy = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lock = Gtk.Image.new_from_icon_name("channel-secure-symbolic")
        lock.add_css_class("muted")
        label = Gtk.Label(label=t("home.privacy"), xalign=0, css_classes=["muted", "tiny"])
        label.set_wrap(True)
        privacy.append(lock)
        privacy.append(label)
        content.append(privacy)


class DevicePage(Gtk.ScrolledWindow):
    def __init__(self, window, device: DeviceInfo) -> None:
        super().__init__()
        self.window = window
        self.device = device
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_hexpand(True)
        self.set_vexpand(True)
        content = _page_box()
        clamp = Adw.Clamp(maximum_size=820, tightening_threshold=620)
        clamp.set_child(content)
        self.set_child(clamp)

        content.append(Gtk.Label(label=t("device.eyebrow"), xalign=0, css_classes=["eyebrow"]))
        title = Gtk.Label(label=device_display_name(device), xalign=0, css_classes=["display"])
        title.set_wrap(True)
        content.append(title)
        content.append(status_pill(device.status))

        if device.status is DeviceStatus.READY:
            body_key = "device.ready_body"
        elif device.status is DeviceStatus.NEEDS_SETUP:
            body_key = "device.needs_driver"
        elif device.status is DeviceStatus.NEEDS_ATTENTION:
            body_key = "device.attention_body"
        else:
            body_key = "device.unsupported_body"
        body = Gtk.Label(label=t(body_key), xalign=0, css_classes=["page-sub"])
        body.set_wrap(True)
        body.set_max_width_chars(64)
        content.append(body)

        if device.reasons:
            reasons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            reasons.set_valign(Gtk.Align.START)
            for reason in device.reasons:
                reasons.append(chip(t(reason), "warn" if reason not in {"reason.ready"} else "ok"))
            content.append(reasons)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        actions.set_margin_top(4)
        primary = Gtk.Button(label=t(device_action_key(device)))
        primary.add_css_class("suggested-action")
        primary.connect("clicked", lambda _b: self.window.device_primary_action(device.id))
        actions.append(primary)
        diagnostics = Gtk.Button(label=t("action.diagnostics"))
        diagnostics.connect("clicked", lambda _b: self.window.show_diagnostics(device.id))
        actions.append(diagnostics)
        content.append(actions)

        content.append(hairline())
        self._identity_section(content)
        self._driver_section(content)
        if device.iface is not None:
            self._interface_section(content)
        self._capabilities_section(content)
        self._advanced_section(content)

        recipe = find_recipe(self.window.detector.recipes, device.recipe_id) if device.recipe_id else None
        if recipe is not None:
            notes = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            notes.append(section_label(t("device.section.notes")))
            summary_key = recipe.summary_key
            if summary_key:
                summary = Gtk.Label(label=t(summary_key), xalign=0, css_classes=["page-sub"])
                summary.set_wrap(True)
                notes.append(summary)
            note_key = recipe.capabilities.get("note_key", "")
            if note_key:
                note = Gtk.Label(label=t(note_key), xalign=0, css_classes=["muted", "tiny"])
                note.set_wrap(True)
                notes.append(note)
            content.append(notes)

    # ------------------------------------------------------------------
    def _identity_section(self, content: Gtk.Box) -> None:
        device = self.device
        content.append(section_label(t("device.section.identity")))
        content.append(key_value(t("device.field.vendor"), device.vendor or t("home.unknown_vendor")))
        content.append(key_value(t("device.field.chipset"), device.family or t("advanced.no_data")))
        if device.usb:
            content.append(key_value(t("device.field.usb_id"), device.usb.usb_id.upper(), mono=True))
            content.append(key_value(t("device.field.confidence"), device.confidence.value))
            if device.usb_stage is not UsbStage.UNKNOWN:
                content.append(key_value("USB stage", device.usb_stage.value, mono=True))

    def _driver_section(self, content: Gtk.Box) -> None:
        device = self.device
        driver = device.driver
        content.append(section_label(t("device.section.driver")))
        content.append(
            key_value(
                t("device.field.driver"),
                (driver.module or t("device.not_available"))
                + (f"  {driver.module_version}" if driver.module_version else ""),
                mono=True,
            )
        )
        if driver.package:
            content.append(
                key_value(
                    t("device.field.package"),
                    f"{driver.package} {driver.package_version}".strip(),
                    mono=True,
                )
            )
        if driver.dkms:
            content.append(key_value(t("device.field.dkms"), driver.dkms_state))
        content.append(
            key_value(
                t("device.field.headers"),
                t("state.yes") if driver.headers_ok else t("state.no"),
            )
        )

    def _interface_section(self, content: Gtk.Box) -> None:
        iface = self.device.iface
        assert iface is not None
        content.append(section_label(t("device.section.interface")))
        content.append(key_value(t("device.field.interface"), f"{iface.name} · {iface.phy}", mono=True))
        content.append(key_value(t("device.field.mac"), iface.mac, mono=True))
        content.append(
            key_value(
                t("device.field.nm_state"),
                t("state.connected") if iface.connected else iface.nm_state or t("state.unknown"),
            )
        )
        content.append(key_value(t("device.field.bands"), format_bands(self.device)))

    def _capabilities_section(self, content: Gtk.Box) -> None:
        device = self.device
        verified = list(device.capabilities_verified)
        advertised = list(device.capabilities_advertised)
        recipe = find_recipe(self.window.detector.recipes, device.recipe_id) if device.recipe_id else None
        unverified = list(recipe.unverified_capabilities) if recipe else []
        content.append(section_label(t("device.section.capabilities")))
        if verified:
            content.append(Gtk.Label(label=t("device.cap.verified"), xalign=0, css_classes=["muted", "tiny"]))
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            for item in verified:
                row.append(chip(t(f"capability.{item}"), "ok"))
            content.append(row)
        if advertised:
            content.append(
                Gtk.Label(label=t("device.cap.advertised"), xalign=0, css_classes=["muted", "tiny"])
            )
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            for item in advertised:
                row.append(chip(item.replace("_", " ")))
            content.append(row)
        if unverified:
            content.append(
                Gtk.Label(label=t("device.cap.unverified"), xalign=0, css_classes=["muted", "tiny"])
            )
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            for item in unverified:
                row.append(chip(t(f"capability.{item}"), "warn"))
            content.append(row)

    def _advanced_section(self, content: Gtk.Box) -> None:
        device = self.device
        expander = Gtk.Expander()
        label = Gtk.Label(label=t("device.section.advanced"), xalign=0, css_classes=["section-title"])
        expander.set_label_widget(label)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.add_css_class("tech-panel")
        warning = Gtk.Label(label=t("device.advanced_warning"), xalign=0, css_classes=["muted", "tiny"])
        warning.set_wrap(True)
        panel.append(warning)
        if device.usb:
            panel.append(key_value("USB path", device.usb.path_name, mono=True))
            panel.append(key_value("Product", device.usb.product or "-", mono=True))
            panel.append(key_value("Manufacturer", device.usb.manufacturer or "-", mono=True))
            panel.append(key_value("Serial", device.usb.serial or "-", mono=True))
            panel.append(key_value("USB class", str(device.usb.device_class), mono=True))
        if device.driver.module_path:
            panel.append(key_value("Module", device.driver.module_path, mono=True))
        if device.driver.conflicts:
            panel.append(key_value("Conflicts", ", ".join(device.driver.conflicts), mono=True))
        if device.iface:
            panel.append(key_value("PHY", device.iface.phy, mono=True))
            if device.iface.supported_modes:
                panel.append(
                    key_value("Modes", ", ".join(device.iface.supported_modes), mono=True)
                )
            if device.iface.rfkill:
                panel.append(
                    key_value(
                        "rfkill",
                        f"{device.iface.rfkill.name} soft={device.iface.rfkill.soft_blocked} "
                        f"hard={device.iface.rfkill.hard_blocked}",
                        mono=True,
                    )
                )
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        copy_button = Gtk.Button(label=t("action.copy"))
        copy_button.connect("clicked", lambda _b: self._copy_details())
        buttons.append(copy_button)
        if (
            self.window.settings.advanced
            and device.iface is not None
            and not device.iface.connected
            and self.window.client.available
        ):
            monitor = Gtk.Button(label=t("monitor.title"))
            monitor.connect("clicked", lambda _b: self.window.monitor_device(device.id))
            buttons.append(monitor)
        panel.append(buttons)
        expander.set_child(panel)
        content.append(hairline())
        content.append(expander)

    def _copy_details(self) -> None:
        device = self.device
        lines = [
            f"Antena {VERSION}",
            f"Device: {device.name} ({device.id})",
            f"USB: {device.usb_id} stage={device.usb_stage.value}",
            f"Vendor: {device.vendor} family={device.family}",
            f"Driver: {device.driver.module} {device.driver.module_version} "
            f"loaded={device.driver.loaded} installed={device.driver.installed_for_running_kernel}",
            f"DKMS: {device.driver.dkms_state}",
            f"Package: {device.driver.package} {device.driver.package_version}",
            f"Headers: {device.driver.headers_ok}",
            f"Interface: {device.interface_name or '-'}",
            f"Status: {device.status.value}",
            f"Reasons: {', '.join(device.reasons)}",
            f"Recipe: {device.recipe_id or '-'}",
        ]
        copy_to_clipboard("\n".join(lines))
        self.window.toast(t("action.copied"))


class DiagnosticsPage(Gtk.ScrolledWindow):
    def __init__(self, window, device_id: str | None) -> None:
        super().__init__()
        self.window = window
        self.device_id = device_id
        self.checks: list[CheckResult] = []
        self.detection = None
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_hexpand(True)
        self.set_vexpand(True)
        content = _page_box()
        self.content = content
        clamp = Adw.Clamp(maximum_size=860, tightening_threshold=640)
        clamp.set_child(content)
        self.set_child(clamp)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        title = Gtk.Label(label=t("diag.title"), xalign=0, css_classes=["display"], hexpand=True)
        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        rerun = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=t("diag.rerun"))
        rerun.add_css_class("flat")
        rerun.connect("clicked", lambda _b: self._run())
        export = Gtk.Button(icon_name="document-save-symbolic", tooltip_text=t("diag.export"))
        export.add_css_class("flat")
        export.connect("clicked", lambda _b: self._export())
        header.append(title)
        header.append(self.spinner)
        header.append(rerun)
        header.append(export)
        content.append(header)
        subtitle = Gtk.Label(label=t("diag.subtitle"), xalign=0, css_classes=["page-sub"])
        subtitle.set_wrap(True)
        content.append(subtitle)
        content.append(hairline())
        self.summary = Gtk.Label(label="", xalign=0, css_classes=["page-sub"])
        self.summary.set_wrap(True)
        content.append(self.summary)
        self.results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        content.append(self.results)
        self._run()

    def _run(self) -> None:
        self.spinner.set_visible(True)
        self.spinner.start()
        self.summary.set_label(t("diag.checking"))
        while True:
            child = self.results.get_first_child()
            if child is None:
                break
            self.results.remove(child)
        run_async(
            lambda: Diagnostics(self.window.detector, helper_available=self.window.client.available).run(
                self.device_id
            ),
            self._show,
            lambda exc: self._error(str(exc)),
        )

    def _error(self, message: str) -> None:
        self.spinner.stop()
        self.spinner.set_visible(False)
        self.summary.set_label(t("error.generic"))

    def _show(self, payload) -> None:
        checks, detection = payload
        self.checks = checks
        self.detection = detection
        self.spinner.stop()
        self.spinner.set_visible(False)
        errors = [item for item in checks if item.status == "error"]
        warnings = [item for item in checks if item.status == "warning"]
        count = len(errors) or len(warnings)
        if count == 1:
            self.summary.set_label(t("diag.issues_one"))
        elif count:
            self.summary.set_label(t("diag.issues", count=count))
        else:
            self.summary.set_label(t("diag.all_ok"))
        for check in checks:
            self.results.append(self._check_row(check))

    def _check_row(self, check: CheckResult) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("check-row")
        icons = {
            "ok": ("object-select-symbolic", "status-icon-ok"),
            "warning": ("dialog-warning-symbolic", "status-icon-warn"),
            "error": ("dialog-error-symbolic", "status-icon-error"),
            "unknown": ("dialog-question-symbolic", "status-icon-unknown"),
        }
        icon_name, css = icons.get(check.status, icons["unknown"])
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.add_css_class(css)
        icon.set_valign(Gtk.Align.START)
        row.append(icon)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        title = Gtk.Label(label=t(check.title_key), xalign=0, css_classes=["section-title"])
        text.append(title)
        if check.explain_key:
            explain = Gtk.Label(label=t(check.explain_key), xalign=0, css_classes=["muted", "tiny"])
            explain.set_wrap(True)
            text.append(explain)
        if check.detail:
            detail = Gtk.Label(label=check.detail, xalign=0, css_classes=["mono"])
            detail.set_wrap(True)
            detail.set_selectable(True)
            text.append(detail)
        if check.technical:
            expander = Gtk.Expander(label=t("diag.technical"))
            technical = Gtk.Label(label=check.technical, xalign=0, css_classes=["mono"])
            technical.set_wrap(True)
            technical.set_selectable(True)
            expander.set_child(technical)
            text.append(expander)
        row.append(text)
        if check.action is not None and self.detection is not None:
            fix = Gtk.Button(label=t("diag.fix"))
            fix.add_css_class("flat")
            fix.set_valign(Gtk.Align.CENTER)
            fix.connect("clicked", lambda _b, item=check: self._apply(item))
            row.append(fix)
        return row

    def _apply(self, check: CheckResult) -> None:
        if self.detection is None:
            return
        device = self.detection.by_id(self.device_id) if self.device_id else None
        if device is None:
            device = next((item for item in self.detection.devices if item.kind == "usb"), None)
        if device is None:
            return
        plan = build_repair_plan(device, self.checks, self.window.detector.recipes)
        if plan.stages:
            self.window.show_repair(plan, device)

    def _export(self) -> None:
        if not self.checks or self.detection is None:
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        dialog = Gtk.FileDialog(title=t("diag.export"))
        dialog.set_initial_name(f"antena-diagnostico-{stamp}.json")
        dialog.save(self.window, None, self._export_done)

    def _export_done(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error:
            return
        path = file.get_path()
        if not path:
            return
        try:
            save_report(build_report(self.detection, self.checks), Path(path))
            self.window.toast(t("diag.export_ok", path=path))
        except OSError:
            self.window.toast(t("diag.export_fail"))


class SettingsPage(Gtk.ScrolledWindow):
    def __init__(self, window) -> None:
        super().__init__()
        self.window = window
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page = Adw.PreferencesPage(margin_top=18)
        page.set_hexpand(True)
        self.set_child(page)

        general = Adw.PreferencesGroup(title=t("settings.title"), description=t("settings.subtitle"))
        page.add(general)
        languages = Gtk.StringList.new([t("settings.auto"), "Español", "English"])
        self.language_row = Adw.ComboRow(title=t("settings.language"), subtitle=t("settings.language_desc"))
        self.language_row.set_model(languages)
        index = {"auto": 0, "es": 1, "en": 2}.get(window.settings.language, 0)
        self.language_row.set_selected(index)
        self.language_row.connect("notify::selected", self._language_changed)
        general.add(self.language_row)

        appearances = Gtk.StringList.new([t("settings.system"), t("settings.light"), t("settings.dark")])
        self.appearance_row = Adw.ComboRow(
            title=t("settings.appearance"), subtitle=t("settings.appearance_desc")
        )
        self.appearance_row.set_model(appearances)
        index = {"system": 0, "light": 1, "dark": 2}.get(window.settings.appearance, 0)
        self.appearance_row.set_selected(index)
        self.appearance_row.connect("notify::selected", self._appearance_changed)
        general.add(self.appearance_row)

        advanced = Adw.PreferencesGroup()
        self.advanced_row = Adw.SwitchRow(
            title=t("settings.advanced"), subtitle=t("settings.advanced_desc")
        )
        self.advanced_row.set_active(window.settings.advanced)
        self.advanced_row.connect("notify::active", self._advanced_changed)
        advanced.add(self.advanced_row)
        page.add(advanced)

        privacy = Adw.PreferencesGroup(title=t("settings.privacy"))
        label = Gtk.Label(label=t("settings.privacy_body"), xalign=0, wrap=True, css_classes=["page-sub"])
        label.set_margin_top(6)
        label.set_margin_bottom(6)
        label.set_margin_start(12)
        label.set_margin_end(12)
        privacy.add(label)
        page.add(privacy)

    def _save(self) -> None:
        from antena.settings import save_settings

        save_settings(self.window.settings)

    def _language_changed(self, row: Adw.ComboRow, _param) -> None:
        mapping = {0: "auto", 1: "es", 2: "en"}
        self.window.settings.language = mapping.get(row.get_selected(), "auto")
        self._save()
        GLib.idle_add(self.window.app.reload_ui)

    def _appearance_changed(self, row: Adw.ComboRow, _param) -> None:
        mapping = {0: "system", 1: "light", 2: "dark"}
        self.window.settings.appearance = mapping.get(row.get_selected(), "system")
        self._save()
        self.window.app.apply_appearance()
        self.window.toast(t("settings.saved"))

    def _advanced_changed(self, row: Adw.SwitchRow, _param) -> None:
        self.window.settings.advanced = row.get_active()
        self._save()
        self.window.toast(t("settings.saved"))
        GLib.idle_add(self.window.app.reload_ui)


class AboutPage(Gtk.ScrolledWindow):
    def __init__(self, window) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content = _page_box()
        content.set_spacing(10)
        clamp = Adw.Clamp(maximum_size=700, tightening_threshold=560)
        clamp.set_child(content)
        self.set_child(clamp)

        art = app_icon_image(92)
        art.set_halign(Gtk.Align.START)
        art.set_margin_bottom(8)
        content.append(art)
        content.append(Gtk.Label(label="Antena", xalign=0, css_classes=["eyebrow"]))
        title = Gtk.Label(label=t("app.tagline"), xalign=0, css_classes=["display"])
        title.set_wrap(True)
        content.append(title)
        content.append(Gtk.Label(label=f"{t('about.version')} {VERSION}", xalign=0, css_classes=["page-sub"]))
        content.append(hairline())

        content.append(key_value(t("about.license"), LICENSE_NAME))
        license_link = Gtk.LinkButton.new_with_label(
            "https://www.gnu.org/licenses/gpl-3.0.html", "GNU GPL v3"
        )
        license_link.set_halign(Gtk.Align.START)
        content.append(license_link)
        if "USUARIO" in PROJECT_URL:
            content.append(key_value(t("about.repo"), t("about.repo_placeholder")))
        else:
            link = Gtk.LinkButton.new_with_label(PROJECT_URL, PROJECT_URL)
            link.set_halign(Gtk.Align.START)
            content.append(link)

        content.append(section_label(t("about.privacy")))
        privacy = Gtk.Label(label=t("about.privacy_body"), xalign=0, css_classes=["page-sub"])
        privacy.set_wrap(True)
        content.append(privacy)
        content.append(section_label(t("about.credits")))
        credits = Gtk.Label(label=t("about.credits_body"), xalign=0, css_classes=["page-sub"])
        credits.set_wrap(True)
        content.append(credits)
        content.append(hairline())
        disclaimer = Gtk.Label(label=t("about.disclaimer"), xalign=0, css_classes=["muted", "tiny"])
        disclaimer.set_wrap(True)
        content.append(disclaimer)
