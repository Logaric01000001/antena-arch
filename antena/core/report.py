"""Informes de diagnóstico exportables, sin secretos ni contraseñas."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from antena.constants import VERSION
from antena.core.detect import DetectionResult
from antena.core.models import CheckResult, DeviceInfo, Environment


def _device_dict(device: DeviceInfo) -> dict[str, Any]:
    return {
        "id": device.id,
        "kind": device.kind,
        "name": device.name,
        "vendor": device.vendor,
        "family": device.family,
        "usb_id": device.usb_id,
        "usb_stage": device.usb_stage.value,
        "status": device.status.value,
        "confidence": device.confidence.value,
        "recipe_id": device.recipe_id,
        "reasons": list(device.reasons),
        "usb": {
            "path": device.usb.path_name,
            "product": device.usb.product,
            "manufacturer": device.usb.manufacturer,
            "serial": device.usb.serial,
            "device_class": device.usb.device_class,
            "interfaces": [list(item) for item in device.usb.interface_classes],
            "driver_modules": list(device.usb.driver_modules),
        }
        if device.usb
        else None,
        "interface": {
            "name": device.iface.name,
            "phy": device.iface.phy,
            "mac": device.iface.mac,
            "type": device.iface.if_type,
            "channel": device.iface.channel,
            "freq_mhz": device.iface.freq_mhz,
            "nm_state": device.iface.nm_state,
            "managed": device.iface.managed,
            "connected": device.iface.connected,
            "rfkill": asdict(device.iface.rfkill) if device.iface.rfkill else None,
            "modes": list(device.iface.supported_modes),
            "bands": list(device.iface.bands),
        }
        if device.iface
        else None,
        "driver": {
            "module": device.driver.module,
            "loaded": device.driver.loaded,
            "module_version": device.driver.module_version,
            "module_path": device.driver.module_path,
            "package": device.driver.package,
            "package_version": device.driver.package_version,
            "dkms_state": device.driver.dkms_state,
            "dkms": [asdict(item) for item in device.driver.dkms],
            "installed_for_running_kernel": device.driver.installed_for_running_kernel,
            "headers_ok": device.driver.headers_ok,
            "headers_package": device.driver.headers_package,
            "conflicts": list(device.driver.conflicts),
        },
        "capabilities": {
            "verified": list(device.capabilities_verified),
            "advertised": list(device.capabilities_advertised),
        },
    }


def _environment_dict(environment: Environment) -> dict[str, Any]:
    return asdict(environment)


def build_report(
    detection: DetectionResult, checks: list[CheckResult] | None = None
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "application": "Antena",
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": _environment_dict(detection.environment),
        "devices": [_device_dict(device) for device in detection.devices],
        "detection_errors": list(detection.errors),
    }
    if checks is not None:
        data["checks"] = [
            {
                "id": check.id,
                "status": check.status,
                "title": check.title_key,
                "detail": check.detail,
                "technical": check.technical,
                "action": check.action.id if check.action else None,
            }
            for check in checks
        ]
    return data


def save_report(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
