"""Interfaz de línea de comandos para pruebas y diagnóstico sin GUI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from antena.constants import PROJECT_URL, VERSION
from antena.core.detect import Detector
from antena.core.diagnose import Diagnostics
from antena.core.report import build_report, save_report
from antena.i18n import current_language, set_language, t
from antena.settings import load_settings


def _print_detection(detector: Detector, as_json: bool, report_path: str | None) -> int:
    detection = detector.detect()
    if as_json or report_path:
        data = build_report(detection)
    if report_path:
        save_report(data, Path(report_path))
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0 if detection.devices else 1
    print(f"Antena {VERSION} · {detection.environment.distro or 'Linux'}")
    print(f"Kernel: {detection.environment.kernel}")
    if not detection.devices:
        print(t("home.title.empty"))
        return 1
    for device in detection.devices:
        print(
            f"- {device.name} [{device.usb_id or device.kind}] "
            f"{t('state.' + device.status.value)}"
        )
        print(
            f"    driver={device.driver.module or '-'} loaded={device.driver.loaded} "
            f"iface={device.interface_name or '-'} recipe={device.recipe_id or '-'}"
        )
        if device.reasons:
            print(f"    {'; '.join(device.reasons)}")
    for error in detection.errors:
        print(f"! {error}", file=sys.stderr)
    return 0


def _print_diagnostics(detector: Detector, device_id: str | None, as_json: bool, report_path: str | None) -> int:
    checks, detection = Diagnostics(detector).run(device_id)
    if as_json or report_path:
        data = build_report(detection, checks)
        if report_path:
            save_report(data, Path(report_path))
        if as_json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
    if as_json:
        return 0 if all(check.status in {"ok", "unknown"} for check in checks) else 1
    symbols = {"ok": "OK", "warning": "AVISO", "error": "ERROR", "unknown": "?"}
    for check in checks:
        print(f"[{symbols.get(check.status, '?')}] {t(check.title_key)}")
        if check.detail:
            print(f"        {check.detail}")
    errors = [check for check in checks if check.status == "error"]
    print()
    if errors:
        print(t("diag.issues", count=len(errors)))
        return 1
    print(t("diag.all_ok"))
    return 0


def _scan(detector: Detector, device_id: str | None, as_json: bool) -> int:
    detection = detector.detect()
    if device_id:
        device = detection.by_id(device_id)
    else:
        device = next(
            (item for item in detection.devices if item.kind == "usb" and item.is_ready),
            None,
        ) or next((item for item in detection.devices if item.is_ready), None)
    if device is None or device.iface is None:
        print(t("scan.failed"), file=sys.stderr)
        return 1
    ok, networks, technical = detector.network.scan(device.iface.name)
    if not ok:
        print(f"{t('scan.failed')}: {technical}", file=sys.stderr)
        return 1
    if as_json:
        print(
            json.dumps(
                {
                    "device": device.id,
                    "interface": device.iface.name,
                    "networks": [
                        {
                            "ssid": item.ssid,
                            "signal": item.signal,
                            "freq_mhz": item.freq_mhz,
                            "band": item.band,
                            "security": item.security,
                        }
                        for item in networks
                    ],
                    "technical": technical,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(f"{device.name} · {device.iface.name} · {t('scan.count', count=len(networks))}")
        for network in networks:
            band = t(f"band.{network.band}") if network.band != "unknown" else t("band.unknown")
            print(f"  {network.ssid}  {band}  {network.signal}%  {network.security}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="antena", description="Wi-Fi sin complicaciones")
    parser.add_argument("--version", action="version", version=f"Antena {VERSION}")
    parser.add_argument("--detect", action="store_true", help="Detecta adaptadores Wi-Fi")
    parser.add_argument("--diagnose", action="store_true", help="Ejecuta el diagnóstico")
    parser.add_argument("--scan", action="store_true", help="Prueba el escaneo de redes")
    parser.add_argument("--device", help="ID de dispositivo (por ejemplo usb:1-1)")
    parser.add_argument("--json", action="store_true", help="Salida JSON")
    parser.add_argument("--report", help="Guarda un informe JSON en esta ruta")
    parser.add_argument("--lang", choices=["es", "en"], help="Idioma de la salida")
    parser.add_argument("--about", action="store_true")
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.lang:
        set_language(args.lang)
    else:
        set_language(settings.effective_language)

    if args.about:
        print(f"Antena {VERSION}")
        print("Licencia: GPL-3.0-or-later")
        print(f"Repositorio: {PROJECT_URL}")
        print(f"Idioma: {current_language()}")
        return 0
    detector = Detector()
    if args.scan:
        return _scan(detector, args.device, args.json)
    if args.diagnose:
        return _print_diagnostics(detector, args.device, args.json, args.report)
    if args.detect or args.json or args.report:
        return _print_detection(detector, args.json, args.report)

    from antena.app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
