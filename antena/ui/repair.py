"""Asistente de configuración con progreso real y prueba de recepción."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from antena.core.executor import PlanExecutor  # noqa: E402
from antena.core.models import (  # noqa: E402
    DeviceInfo,
    Plan,
    PlanResult,
    StageEvent,
)
from antena.core.planner import plan_needs_helper  # noqa: E402
from antena.i18n import t  # noqa: E402
from antena.ui.widgets import hairline, run_async, show_alert  # noqa: E402


class StageRow(Gtk.Box):
    def __init__(self, key: str) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.key = key
        self.add_css_class("stage-row")
        self.icon_box = Gtk.Box(valign=Gtk.Align.START)
        self.icon_box.set_size_request(20, 20)
        self.append(self.icon_box)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        self.title = Gtk.Label(label=t(key), xalign=0, css_classes=["section-title"])
        self.detail = Gtk.Label(label="", xalign=0, css_classes=["muted", "tiny"])
        self.detail.set_wrap(True)
        self.detail.set_visible(False)
        self.technical = Gtk.Label(label="", xalign=0, css_classes=["mono"])
        self.technical.set_wrap(True)
        self.technical.set_selectable(True)
        self.technical.set_visible(False)
        text.append(self.title)
        text.append(self.detail)
        text.append(self.technical)
        self.append(text)
        self.status = Gtk.Label(label=t("stage.status.pending"), css_classes=["muted", "tiny"])
        self.status.set_valign(Gtk.Align.START)
        self.append(self.status)
        self._set_state("pending")

    def _clear_icon(self) -> None:
        child = self.icon_box.get_first_child()
        while child is not None:
            self.icon_box.remove(child)
            child = self.icon_box.get_first_child()

    def _set_state(self, state: str) -> None:
        self._clear_icon()
        if state == "running":
            spinner = Gtk.Spinner()
            spinner.start()
            self.icon_box.append(spinner)
        elif state == "ok":
            icon = Gtk.Image.new_from_icon_name("object-select-symbolic")
            icon.add_css_class("status-icon-ok")
            self.icon_box.append(icon)
        elif state == "failed":
            icon = Gtk.Image.new_from_icon_name("dialog-error-symbolic")
            icon.add_css_class("status-icon-error")
            self.icon_box.append(icon)
        elif state == "cancelled":
            icon = Gtk.Image.new_from_icon_name("process-stop-symbolic")
            self.icon_box.append(icon)
        elif state == "skipped":
            label = Gtk.Label(label="–", css_classes=["muted"])
            self.icon_box.append(label)
        else:
            label = Gtk.Label(label="•", css_classes=["muted"])
            self.icon_box.append(label)
        self.status.set_label(t(f"stage.status.{state}"))
        if state == "running":
            self.status.remove_css_class("muted")
        else:
            self.status.add_css_class("muted")

    def update(self, event: StageEvent) -> None:
        self._set_state(event.state)
        if event.message:
            self.detail.set_label(event.message)
            self.detail.set_visible(True)
        if event.technical:
            self.technical.set_label(event.technical)
            self.technical.set_visible(event.state == "failed")
        if event.state == "failed":
            self.technical.set_visible(True)


class RepairPage(Gtk.ScrolledWindow):
    def __init__(self, window, plan: Plan, device: DeviceInfo) -> None:
        super().__init__()
        self.window = window
        self.plan = plan
        self.device = device
        self.cancel_event = threading.Event()
        self.rows: list[StageRow] = []
        self.running = False
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=30,
            margin_bottom=34,
            margin_start=38,
            margin_end=38,
        )
        clamp = Adw.Clamp(maximum_size=780, tightening_threshold=580)
        clamp.set_child(self.content)
        self.set_child(clamp)

        title_key = {
            "repair": "wizard.repair.title",
            "check": "action.test_scan",
        }.get(plan.kind, "wizard.setup.title")
        self.content.append(Gtk.Label(label=t("device.eyebrow"), xalign=0, css_classes=["eyebrow"]))
        title = Gtk.Label(label=t(title_key), xalign=0, css_classes=["display"])
        title.set_wrap(True)
        self.content.append(title)
        subtitle = Gtk.Label(label=t("wizard.subtitle"), xalign=0, css_classes=["page-sub"])
        subtitle.set_wrap(True)
        self.content.append(subtitle)
        self.content.append(hairline())
        self.content.append(Gtk.Label(label=t("wizard.changes"), xalign=0, css_classes=["section-title"]))

        self.stage_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for index, stage in enumerate(plan.stages):
            row = StageRow(stage.key)
            self.rows.append(row)
            self.stage_box.append(row)
            if index < len(plan.stages) - 1:
                self.stage_box.append(hairline())
        self.content.append(self.stage_box)

        if not plan.stages:
            self.content.append(Gtk.Label(label=t("diag.all_ok"), xalign=0, css_classes=["page-sub"]))

        auth = Gtk.Label(label=t("wizard.auth"), xalign=0, css_classes=["muted", "tiny"])
        auth.set_wrap(True)
        self.content.append(auth)

        self.banner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.banner.set_visible(False)
        self.banner_label = Gtk.Label(label="", xalign=0)
        self.banner_label.set_wrap(True)
        self.banner.append(self.banner_label)
        self.banner_technical = Gtk.Label(label="", xalign=0, css_classes=["mono"])
        self.banner_technical.set_wrap(True)
        self.banner_technical.set_selectable(True)
        self.banner.append(self.banner_technical)
        self.content.append(self.banner)

        self.buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.start_button = Gtk.Button(label=t("wizard.start"))
        self.start_button.add_css_class("suggested-action")
        self.start_button.connect("clicked", lambda _b: self._confirm())
        self.buttons.append(self.start_button)
        self.cancel_button = Gtk.Button(label=t("wizard.cancel"))
        self.cancel_button.set_visible(False)
        self.cancel_button.connect("clicked", lambda _b: self._cancel())
        self.buttons.append(self.cancel_button)
        self.result_button = Gtk.Button(label=t("wizard.ready"))
        self.result_button.add_css_class("suggested-action")
        self.result_button.set_visible(False)
        self.result_button.connect("clicked", lambda _b: self._show_result())
        self.buttons.append(self.result_button)
        self.content.append(self.buttons)

        self.technical_expander = Gtk.Expander(label=t("wizard.log"))
        self.technical_expander.set_visible(False)
        self.content.append(self.technical_expander)

    def _confirm(self) -> None:
        if not self.plan.stages:
            return
        if plan_needs_helper(self.plan) and not self.window.client.available:
            show_alert(
                self.window,
                t("error.no_helper"),
                t("error.no_helper_body"),
            )
            return
        changes = "\n".join(f"• {t(stage.key)}" for stage in self.plan.stages)
        show_alert(
            self.window,
            t("wizard.changes"),
            f"{changes}\n\n{t('wizard.auth')}",
            confirm_label=t("wizard.start"),
            on_confirm=self._start,
        )

    def _start(self) -> None:
        if self.running:
            return
        self.running = True
        self.cancel_event.clear()
        self.start_button.set_sensitive(False)
        self.cancel_button.set_visible(True)
        self.result_button.set_visible(False)
        self.banner.set_visible(False)
        self.technical_expander.set_visible(False)
        for row in self.rows:
            row._set_state("pending")
            row.detail.set_visible(False)
            row.technical.set_visible(False)

        executor = PlanExecutor(
            self.window.detector,
            self.window.client,
            on_event=lambda event: GLib.idle_add(self._on_event, event),
        )

        def work() -> PlanResult:
            return executor.execute(self.plan, self.cancel_event)

        run_async(work, self._finished, self._crashed)

    def _on_event(self, event: StageEvent) -> None:
        if 0 <= event.index < len(self.rows):
            self.rows[event.index].update(event)

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.cancel_button.set_sensitive(False)
        for row in self.rows:
            if row.status.get_label() == t("stage.status.running"):
                row._set_state("cancelled")

    def _crashed(self, exc: Exception) -> None:
        self.running = False
        self.cancel_button.set_visible(False)
        self.start_button.set_sensitive(True)
        self._show_banner(False, t("wizard.failed"), str(exc))

    def _finished(self, result: PlanResult) -> None:
        self.running = False
        self.cancel_button.set_visible(False)
        self.start_button.set_sensitive(True)
        if result.cancelled:
            self._show_banner(False, t("wizard.cancelled"), "")
            return
        if result.ok:
            self._show_banner(True, t("wizard.done"), "")
            self.result_button.set_visible(True)
            self.start_button.set_visible(False)
            self.window.refresh(keep_page=False)
        else:
            self._show_banner(False, t("wizard.failed"), result.message or "")
            if result.technical:
                label = Gtk.Label(label=result.technical, xalign=0, css_classes=["mono"])
                label.set_wrap(True)
                label.set_selectable(True)
                self.technical_expander.set_child(label)
                self.technical_expander.set_visible(True)
            retry = Gtk.Button(label=t("action.retry"))
            retry.add_css_class("flat")
            retry.connect("clicked", lambda _b: self.window.device_primary_action(self.device.id))
            self.buttons.append(retry)

    def _show_banner(self, ok: bool, title: str, detail: str) -> None:
        self.banner.set_visible(True)
        self.banner.add_css_class("banner-ok" if ok else "banner-error")
        self.banner_label.set_label(title)
        self.banner_technical.set_label(detail)
        self.banner_technical.set_visible(bool(detail))

    def _show_result(self) -> None:
        self.window.show_device(self.device.id)


class ScanDialog(Adw.Dialog):
    def __init__(self, window, device: DeviceInfo) -> None:
        super().__init__()
        self.window = window
        self.device = device
        self.set_content_width(620)
        self.set_content_height(430)
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=t("scan.title"), subtitle=device.interface_name))
        close = Gtk.Button(label=t("scan.close"))
        close.connect("clicked", lambda _b: self.close())
        header.pack_end(close)
        toolbar.add_top_bar(header)
        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=20,
            margin_bottom=22,
            margin_start=24,
            margin_end=24,
        )
        subtitle = Gtk.Label(label=t("scan.body"), xalign=0, css_classes=["page-sub"])
        subtitle.set_wrap(True)
        content.append(subtitle)
        self.spinner = Gtk.Spinner()
        self.spinner.set_halign(Gtk.Align.START)
        self.status = Gtk.Label(label=t("scan.running"), xalign=0)
        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        status_row.append(self.spinner)
        status_row.append(self.status)
        content.append(status_row)
        self.spinner.start()
        self.results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_child(self.results)
        content.append(scroll)
        toolbar.set_content(content)
        self.set_child(toolbar)
        self._run()

    def _run(self) -> None:
        if self.device.iface is None:
            self._fail(t("scan.failed"))
            return
        run_async(
            lambda: self.window.detector.network.scan(self.device.iface.name),
            self._show,
            lambda exc: self._fail(str(exc)),
        )

    def _show(self, payload) -> None:
        ok, networks, technical = payload
        self.spinner.stop()
        self.spinner.set_visible(False)
        if not ok:
            self._fail(technical)
            return
        if not networks:
            self.status.set_label(t("scan.empty"))
            return
        self.status.set_label(
            t("scan.count_one") if len(networks) == 1 else t("scan.count", count=len(networks))
        )
        for network in networks:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.add_css_class("device-row")
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
            name = Gtk.Label(label=network.ssid, xalign=0, css_classes=["section-title"])
            band = t(f"band.{network.band}") if network.band in {"2.4ghz", "5ghz", "6ghz"} else t("band.unknown")
            meta = Gtk.Label(
                label=f"{band} · {network.signal}% · {network.security or '—'}",
                xalign=0,
                css_classes=["muted", "tiny"],
            )
            text.append(name)
            text.append(meta)
            row.append(text)
            if network.in_use:
                row.append(Gtk.Label(label="●", css_classes=["status-icon-ok"]))
            self.results.append(row)

    def _fail(self, technical: str) -> None:
        self.spinner.stop()
        self.spinner.set_visible(False)
        self.status.set_label(f"{t('scan.failed')} {technical}".strip())


class MonitorDialog(Adw.Dialog):
    def __init__(self, window, device: DeviceInfo) -> None:
        super().__init__()
        self.window = window
        self.device = device
        self.set_content_width(560)
        self.set_content_height(460)
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=t("monitor.title")))
        close = Gtk.Button(label=t("action.close"))
        close.connect("clicked", lambda _b: self.close())
        header.pack_end(close)
        toolbar.add_top_bar(header)
        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=20,
            margin_bottom=22,
            margin_start=24,
            margin_end=24,
        )
        body = Gtk.Label(label=t("monitor.body"), xalign=0, css_classes=["page-sub"])
        body.set_wrap(True)
        content.append(body)
        note = Gtk.Label(label=t("monitor.reason"), xalign=0, css_classes=["muted", "tiny"])
        note.set_wrap(True)
        content.append(note)
        content.append(hairline())
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        channel_label = Gtk.Label(label=t("monitor.channel"), xalign=0)
        self.channel = Gtk.SpinButton.new_with_range(1, 196, 1)
        self.channel.set_value(6)
        seconds_label = Gtk.Label(label=t("monitor.seconds"), xalign=0)
        self.seconds = Gtk.SpinButton.new_with_range(3, 15, 1)
        self.seconds.set_value(8)
        controls.append(channel_label)
        controls.append(self.channel)
        controls.append(seconds_label)
        controls.append(self.seconds)
        content.append(controls)
        self.start_button = Gtk.Button(label=t("monitor.start"))
        self.start_button.add_css_class("suggested-action")
        self.start_button.set_halign(Gtk.Align.START)
        self.start_button.connect("clicked", lambda _b: self._start())
        content.append(self.start_button)
        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        self.status = Gtk.Label(label="", xalign=0, wrap=True)
        status_row.append(self.spinner)
        status_row.append(self.status)
        content.append(status_row)
        self.detail = Gtk.Label(label="", xalign=0, css_classes=["mono"])
        self.detail.set_wrap(True)
        self.detail.set_selectable(True)
        content.append(self.detail)
        toolbar.set_content(content)
        self.set_child(toolbar)

    def _start(self) -> None:
        self.start_button.set_sensitive(False)
        self.spinner.set_visible(True)
        self.spinner.start()
        self.status.set_label(t("monitor.running"))
        payload = {
            "iface": self.device.interface_name,
            "channel": int(self.channel.get_value()),
            "seconds": int(self.seconds.get_value()),
        }
        run_async(
            lambda: self.window.client.call("monitor_probe", payload),
            self._done,
            lambda exc: self._fail(str(exc)),
        )

    def _done(self, result) -> None:
        self.spinner.stop()
        self.spinner.set_visible(False)
        self.start_button.set_sensitive(True)
        if result.ok:
            beacons = result.data.get("beacons", 0)
            packets = result.data.get("packets", 0)
            self.status.set_label(t("monitor.result", beacons=beacons, packets=packets))
        else:
            self._fail(result.message or t("monitor.failed"))

    def _fail(self, message: str) -> None:
        self.spinner.stop()
        self.spinner.set_visible(False)
        self.start_button.set_sensitive(True)
        self.status.set_label(t("monitor.failed"))
        self.detail.set_label(message)
