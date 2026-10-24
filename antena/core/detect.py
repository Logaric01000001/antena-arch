"""Motor de detección: une sysfs, NetworkManager, módulos y catálogo."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from antena.core.catalog import Recipe, load_recipes
from antena.core.drivers import DriverInspector, kernel_headers_package
from antena.core.models import (
    Confidence,
    DeviceInfo,
    DeviceStatus,
    Environment,
    UsbRecord,
    UsbStage,
    WifiInterface,
)
from antena.core.network import NetworkTools
from antena.core.runner import CommandRunner, Runner
from antena.core.sysfs import Sysfs, SystemPaths

WIFI_VENDORS = frozenset(
    {
        "0bda",  # Realtek
        "0e8d",  # MediaTek / Ralink
        "148f",  # Ralink
        "0cf3",  # Qualcomm Atheros
        "0846",  # Netgear
        "2357",  # TP-Link
        "2001",  # D-Link
        "7392",  # Edimax
        "0b05",  # ASUS
        "050d",  # Belkin
        "0411",  # Buffalo
        "13b1",  # Linksys
        "0586",  # ZyXEL
        "04bb",  # I-O Data
        "0e66",  # Hawking
        "1b75",  # Ovislink
        "1740",  # Edimax
    }
)
BLUETOOTH_DRIVERS = frozenset({"btusb", "btintel", "btqca", "btmtk", "btbcm", "btusb_mtk"})
BLUETOOTH_HINTS = ("bluetooth", "bt radio", "wireless bluetooth")


@dataclass
class DetectionResult:
    devices: list[DeviceInfo] = field(default_factory=list)
    environment: Environment = field(default_factory=Environment)
    errors: list[str] = field(default_factory=list)

    def by_id(self, device_id: str) -> DeviceInfo | None:
        for device in self.devices:
            if device.id == device_id:
                return device
        return None

    @property
    def ready_usb(self) -> list[DeviceInfo]:
        return [item for item in self.devices if item.kind == "usb" and item.status is DeviceStatus.READY]


class Detector:
    def __init__(
        self,
        paths: SystemPaths | None = None,
        runner: Runner | None = None,
        recipes: tuple[Recipe, ...] | None = None,
    ) -> None:
        self.paths = paths or SystemPaths()
        self.runner = runner or CommandRunner()
        self.sysfs = Sysfs(self.paths)
        self.network = NetworkTools(self.sysfs, self.runner)
        self.drivers = DriverInspector(self.sysfs, self.runner)
        self._recipes = recipes
        self._recipe_error = ""

    @property
    def recipes(self) -> tuple[Recipe, ...]:
        if self._recipes is None:
            try:
                self._recipes = load_recipes(self.paths.source_catalog)
            except Exception as exc:  # catálogo roto: se informa, no se oculta
                self._recipe_error = str(exc)
                self._recipes = ()
        return self._recipes

    # ------------------------------------------------------------------
    def environment(self) -> Environment:
        kernel = self.sysfs.kernel_version() or os.uname().release
        release = ""
        try:
            for line in self.paths.os_release.read_text(encoding="utf-8").splitlines():
                if line.startswith("PRETTY_NAME="):
                    release = line.split("=", 1)[1].strip().strip('"')
                    break
        except OSError:
            release = ""
        return Environment(
            kernel=kernel,
            distro=release,
            dkms_available=self.runner.which("dkms") is not None,
            usb_modeswitch_available=self.runner.which("usb_modeswitch") is not None,
            nm_available=self.runner.which("nmcli") is not None,
            iw_available=self.runner.which("iw") is not None,
            tcpdump_available=self.runner.which("tcpdump") is not None,
            headers_ok=self.sysfs.headers_ok(kernel),
            headers_package=kernel_headers_package(kernel),
            pacman_available=self.runner.which("pacman") is not None,
        )

    def detect(self) -> DetectionResult:
        env = self.environment()
        result = DetectionResult(environment=env)
        if self._recipe_error:
            result.errors.append(f"catálogo: {self._recipe_error}")
        if not self.paths.sys.is_dir():
            result.errors.append(f"sysfs no disponible: {self.paths.sys}")
            return result

        rfkill = self.sysfs.rfkill()
        usb_devices = self.sysfs.usb_devices()
        handled_interfaces: set[str] = set()

        for usb in usb_devices:
            if self._is_bluetooth(usb):
                continue
            device = self._usb_device(usb, env, rfkill)
            if device is None:
                continue
            result.devices.append(device)
            if device.iface:
                handled_interfaces.add(device.iface.name)

        for name in self.sysfs.net_names():
            if name in handled_interfaces:
                continue
            if not self.sysfs.net_is_wireless(name):
                continue
            if self.sysfs.net_is_usb(name):
                continue
            iface = self.network.wifi_interface(name, rfkill)
            if iface is None:
                continue
            result.devices.append(self._internal_device(iface, env))

        result.devices.sort(key=lambda item: (item.kind != "pci", item.name.lower()))
        return result

    # ------------------------------------------------------------------
    def _usb_device(
        self,
        usb: UsbRecord,
        env: Environment,
        rfkill: Iterable,
    ) -> DeviceInfo | None:
        iface = self._primary_interface(usb, rfkill)
        driver_module = self._bound_driver(usb, iface)
        aliases = self.drivers.alias_candidates(usb.modalias, env.kernel)
        recipe = self._match_recipe(usb, driver_module, aliases)
        evidence = bool(iface) or recipe is not None or self._looks_like_wifi(usb, aliases)
        if not evidence:
            return None

        stage = recipe.stage_for(usb.usb_id) if recipe else UsbStage.UNKNOWN
        # La clase USB es un hecho físico y prevalece sobre la tabla de IDs.
        if usb.is_storage:
            stage = UsbStage.STORAGE
        elif stage is UsbStage.UNKNOWN and iface is not None:
            stage = UsbStage.OPERATIONAL

        module = (
            recipe.primary_module
            if recipe and recipe.primary_module
            else driver_module or (aliases[0] if aliases else "")
        )
        if recipe:
            conflict_prefix = recipe.dkms_package.split("-")[0] if recipe.dkms_package else ""
            driver = self.drivers.inspect(
                module,
                package=recipe.package,
                dkms_package=recipe.dkms_package,
                alternatives=recipe.modules,
                expected_dkms=recipe.dkms_package,
                conflict_prefixes=(conflict_prefix,) if conflict_prefix else (),
            )
        else:
            driver = self.drivers.inspect(module, conflict_prefixes=())

        status, reasons = self._status_for(usb, iface, driver, recipe, stage, env)
        verified: tuple[str, ...] = ()
        advertised: tuple[str, ...] = ()
        if recipe:
            verified = recipe.verified_capabilities if status is DeviceStatus.READY else ()
            advertised = iface.supported_modes if iface else recipe.advertised_modes
        elif iface:
            advertised = iface.supported_modes

        name = recipe.name if recipe else usb.display_name
        if recipe and recipe.family:
            name = recipe.name
        return DeviceInfo(
            id=f"usb:{usb.path_name}",
            kind="usb",
            name=name,
            vendor=recipe.vendor if recipe else usb.manufacturer,
            family=recipe.family if recipe else "",
            usb=usb,
            iface=iface,
            usb_stage=stage,
            driver=driver,
            recipe_id=recipe.id if recipe else None,
            confidence=recipe.match_confidence(usb, driver_module) if recipe else Confidence.NONE,
            status=status,
            reasons=tuple(reasons),
            capabilities_advertised=tuple(advertised),
            capabilities_verified=tuple(verified),
        )

    def _internal_device(self, iface: WifiInterface, env: Environment) -> DeviceInfo:
        driver_module = self.sysfs.net_driver(iface.name)
        recipe = next((item for item in self.recipes if item.matches_driver(driver_module)), None)
        driver = self.drivers.inspect(
            driver_module,
            package=recipe.package if recipe else "",
            alternatives=recipe.modules if recipe else (),
            conflict_prefixes=(),
        )
        reasons: list[str] = []
        status = DeviceStatus.READY
        if iface.rfkill and iface.rfkill.hard_blocked:
            status = DeviceStatus.NEEDS_ATTENTION
            reasons.append("reason.rfkill_hard_blocked")
        elif iface.blocked:
            status = DeviceStatus.NEEDS_ATTENTION
            reasons.append("reason.rfkill_blocked")
        elif not iface.managed:
            status = DeviceStatus.NEEDS_ATTENTION
            reasons.append("reason.nm_unmanaged")
        else:
            reasons.append("reason.ready")
        pci_id = self.sysfs.pci_id(iface.name)
        return DeviceInfo(
            id=f"pci:{pci_id or iface.name}",
            kind="pci",
            name=recipe.name if recipe and recipe.id == "kernel-iwlwifi" else f"Wi-Fi interna · {iface.name}",
            vendor=recipe.vendor if recipe else "",
            family=recipe.family if recipe else driver_module,
            iface=iface,
            driver=driver,
            recipe_id=recipe.id if recipe else None,
            confidence=Confidence.CONFIRMED if recipe and iface else Confidence.NONE,
            status=status,
            reasons=tuple(reasons),
            capabilities_advertised=iface.supported_modes,
            capabilities_verified=(),
            internal=True,
        )

    def _primary_interface(self, usb: UsbRecord, rfkill: Iterable) -> WifiInterface | None:
        for name in usb.net_names:
            iface = self.network.wifi_interface(name, list(rfkill))
            if iface is not None:
                return iface
        return None

    def _match_recipe(
        self, usb: UsbRecord, driver_module: str, aliases: tuple[str, ...]
    ) -> Recipe | None:
        best: tuple[int, Recipe] | None = None
        for recipe in self.recipes:
            score = 0
            confidence = recipe.match_confidence(usb, driver_module)
            score += {
                Confidence.CONFIRMED: 4,
                Confidence.LIKELY: 3,
                Confidence.WEAK: 2,
                Confidence.NONE: 0,
            }[confidence]
            if driver_module and recipe.matches_driver(driver_module):
                score += 2
            if any(alias in recipe.drivers for alias in aliases):
                score += 1
            if score >= 3 and (best is None or score > best[0]):
                best = (score, recipe)
        return best[1] if best else None

    def _bound_driver(self, usb: UsbRecord, iface: WifiInterface | None) -> str:
        for module in usb.driver_modules:
            if module not in BLUETOOTH_DRIVERS:
                return module
        if iface is not None:
            candidate = self.sysfs.net_driver(iface.name)
            if candidate and candidate != "usb":
                return candidate
        return ""

    def _status_for(
        self,
        usb: UsbRecord,
        iface: WifiInterface | None,
        driver,
        recipe: Recipe | None,
        stage: UsbStage,
        env: Environment,
    ) -> tuple[DeviceStatus, list[str]]:
        reasons: list[str] = []
        if stage is UsbStage.STORAGE:
            return DeviceStatus.NEEDS_SETUP, ["reason.storage_mode"]
        if recipe is None:
            if iface is not None:
                if iface.rfkill and iface.rfkill.hard_blocked:
                    return DeviceStatus.NEEDS_ATTENTION, ["reason.rfkill_hard_blocked"]
                if iface.blocked:
                    return DeviceStatus.NEEDS_ATTENTION, ["reason.rfkill_blocked"]
                if not iface.managed:
                    return DeviceStatus.NEEDS_ATTENTION, ["reason.nm_unmanaged"]
                return DeviceStatus.READY, ["reason.ready", "reason.generic_driver"]
            return DeviceStatus.UNSUPPORTED, ["reason.unknown_chipset"]
        if driver.conflicts:
            reasons.append("reason.driver_conflict")
        if not driver.installed_for_running_kernel and not recipe.is_kernel_native:
            reasons.append("reason.driver_missing")
            return DeviceStatus.NEEDS_SETUP, reasons
        if recipe.firmware_dest and not self._firmware_present(recipe.firmware_dest):
            reasons.append("reason.firmware_missing")
            return DeviceStatus.NEEDS_ATTENTION, reasons
        if iface is None:
            if stage is UsbStage.TRANSITIONAL:
                reasons.append("reason.reconnecting")
            if driver.loaded:
                reasons.append("reason.driver_loaded_no_interface")
            else:
                reasons.append("reason.driver_not_loaded")
            return DeviceStatus.NEEDS_ATTENTION, reasons
        if iface.rfkill and iface.rfkill.hard_blocked:
            reasons.append("reason.rfkill_hard_blocked")
            return DeviceStatus.NEEDS_ATTENTION, reasons
        if iface.blocked:
            reasons.append("reason.rfkill_blocked")
            return DeviceStatus.NEEDS_ATTENTION, reasons
        if not iface.managed:
            reasons.append("reason.nm_unmanaged")
            return DeviceStatus.NEEDS_ATTENTION, reasons
        if recipe.tested_kernels and env.kernel not in recipe.tested_kernels:
            reasons.append("reason.kernel_untested")
        if not driver.loaded:
            reasons.append("reason.driver_not_loaded")
            return DeviceStatus.NEEDS_ATTENTION, reasons
        reasons.append("reason.ready")
        return DeviceStatus.READY, reasons

    def _firmware_present(self, dest: str) -> bool:
        if not dest:
            return True
        path = Path(dest)
        # En pruebas, /lib/firmware apunta a un árbol simulado.
        for prefix in ("/lib/firmware", "/usr/lib/firmware"):
            if str(path) == prefix:
                return self.paths.firmware.exists()
            if str(path).startswith(prefix + "/"):
                relative = str(path)[len(prefix) + 1 :]
                return (self.paths.firmware / relative).exists()
        return path.exists()

    def _looks_like_wifi(self, usb: UsbRecord, aliases: tuple[str, ...]) -> bool:
        if usb.vid in WIFI_VENDORS and not usb.is_storage:
            if any(cls == 0xFF for cls, _, _ in usb.interface_classes) or not usb.interface_classes:
                return True
        if any("cfg80211" in item or "wifi" in item for item in aliases):
            return True
        return False

    def _is_bluetooth(self, usb: UsbRecord) -> bool:
        text = f"{usb.product} {usb.manufacturer}".lower()
        if any(hint in text for hint in BLUETOOTH_HINTS):
            return True
        if any(module in BLUETOOTH_DRIVERS for module in usb.driver_modules):
            return True
        classes = usb.interface_classes
        if usb.device_class == 0xE0 and classes:
            if all(cls == 0xE0 and sub == 1 and proto == 1 for cls, sub, proto in classes):
                # Clase 0xE0/01/01 la comparten Bluetooth y Wi-Fi. Sin interfaz
                # de red, solo se descarta si no hay receta ni alias de red.
                return not usb.net_names and not any("wifi" in item for item in usb.driver_modules)
        return False


def detect(paths: SystemPaths | None = None, runner: Runner | None = None) -> DetectionResult:
    return Detector(paths=paths, runner=runner).detect()
