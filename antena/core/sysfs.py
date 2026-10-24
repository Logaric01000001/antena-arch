"""Lectura de sysfs y enumeración de hardware.

Todas las rutas son inyectables para poder probar con árboles sysfs simulados.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from antena.core.models import RfkillState, UsbRecord


@dataclass(frozen=True)
class SystemPaths:
    sys: Path = Path("/sys")
    proc: Path = Path("/proc")
    modules: Path = Path("/lib/modules")
    firmware: Path = Path("/lib/firmware")
    usb_ids: Path = Path("/usr/share/hwdata/usb.ids")
    os_release: Path = Path("/etc/os-release")
    source_catalog: Path | None = None


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, ValueError):
        return ""


def read_int(path: Path, default: int = 0) -> int:
    raw = read_text(path)
    if not raw:
        return default
    token = raw.split()[0]
    try:
        return int(token, 0)
    except ValueError:
        # sysfs escribe clases USB en hexadecimal sin prefijo ("ff", "08").
        try:
            return int(token, 16)
        except ValueError:
            return default


def link_name(path: Path) -> str:
    try:
        return path.resolve().name
    except OSError:
        return ""


class Sysfs:
    def __init__(self, paths: SystemPaths | None = None) -> None:
        self.paths = paths or SystemPaths()

    # -- utilidades -----------------------------------------------------
    def usb_devices(self) -> list[UsbRecord]:
        base = self.paths.sys / "bus" / "usb" / "devices"
        records: list[UsbRecord] = []
        if not base.is_dir():
            return records
        for entry in sorted(base.iterdir(), key=lambda item: item.name):
            # Los directorios de interfaz contienen ":" y los root hubs no
            # contienen "-"; ninguno es un adaptador físico.
            if ":" in entry.name or "-" not in entry.name:
                continue
            vid = read_text(entry / "idVendor")
            pid = read_text(entry / "idProduct")
            if not vid or not pid:
                continue
            interface_classes: list[tuple[int, int, int]] = []
            drivers: list[str] = []
            for child in sorted(entry.glob(f"{entry.name}:*")):
                interface_classes.append(
                    (
                        read_int(child / "bInterfaceClass", -1),
                        read_int(child / "bInterfaceSubClass", -1),
                        read_int(child / "bInterfaceProtocol", -1),
                    )
                )
                driver = link_name(child / "driver")
                if driver and driver != "usb":
                    drivers.append(driver)
            net_dir = entry / "net"
            net_names = tuple(sorted(item.name for item in net_dir.iterdir())) if net_dir.is_dir() else ()
            records.append(
                UsbRecord(
                    path_name=entry.name,
                    vid=vid.lower(),
                    pid=pid.lower(),
                    product=read_text(entry / "product"),
                    manufacturer=read_text(entry / "manufacturer"),
                    serial=read_text(entry / "serial"),
                    device_class=read_int(entry / "bDeviceClass", 0),
                    interface_classes=tuple(interface_classes),
                    net_names=net_names,
                    driver_modules=tuple(dict.fromkeys(drivers)),
                    speed=read_text(entry / "speed"),
                    busnum=read_text(entry / "busnum"),
                    devnum=read_text(entry / "devnum"),
                    modalias=read_text(entry / "modalias"),
                )
            )
        return records

    def usb_by_id(self, usb_id: str) -> list[UsbRecord]:
        wanted = usb_id.lower()
        return [device for device in self.usb_devices() if device.usb_id == wanted]

    def wifi_phys(self) -> list[str]:
        base = self.paths.sys / "class" / "ieee80211"
        if not base.is_dir():
            return []
        return sorted((item.name for item in base.iterdir() if item.name.startswith("phy")), key=_phy_order)

    def rfkill(self) -> list[RfkillState]:
        base = self.paths.sys / "class" / "rfkill"
        if not base.is_dir():
            return []
        states: list[RfkillState] = []
        for entry in base.iterdir():
            if not entry.name.startswith("rfkill"):
                continue
            try:
                index = int(entry.name.removeprefix("rfkill"))
            except ValueError:
                continue
            states.append(
                RfkillState(
                    index=index,
                    kind=read_text(entry / "type"),
                    name=read_text(entry / "name"),
                    soft_blocked=read_int(entry / "soft") == 1,
                    hard_blocked=read_int(entry / "hard") == 1,
                )
            )
        return sorted(states, key=lambda item: item.index)

    def net_names(self) -> list[str]:
        base = self.paths.sys / "class" / "net"
        if not base.is_dir():
            return []
        return sorted(item.name for item in base.iterdir())

    def net_is_wireless(self, name: str) -> bool:
        net = self.paths.sys / "class" / "net" / name
        return (net / "phy80211").exists() or (net / "wireless").is_dir()

    def net_phy(self, name: str) -> str:
        return link_name(self.paths.sys / "class" / "net" / name / "phy80211")

    def net_is_usb(self, name: str) -> bool:
        try:
            resolved = (self.paths.sys / "class" / "net" / name / "device").resolve()
        except OSError:
            return False
        return "usb" in resolved.parts

    def net_driver(self, name: str) -> str:
        return link_name(self.paths.sys / "class" / "net" / name / "device" / "driver")

    def net_mac(self, name: str) -> str:
        return read_text(self.paths.sys / "class" / "net" / name / "address")

    def net_type(self, name: str) -> str:
        return read_text(self.paths.sys / "class" / "net" / name / "type")

    def pci_id(self, name: str) -> str:
        uevent = read_text(self.paths.sys / "class" / "net" / name / "device" / "uevent")
        for line in uevent.splitlines():
            if line.startswith("PCI_ID="):
                return line.split("=", 1)[1].strip().lower()
        vendor = read_text(self.paths.sys / "class" / "net" / name / "device" / "vendor")
        device = read_text(self.paths.sys / "class" / "net" / name / "device" / "device")
        if vendor and device:
            return f"{vendor.removeprefix('0x')}:{device.removeprefix('0x')}".lower()
        return ""

    def headers_ok(self, kernel: str) -> bool:
        return (self.paths.modules / kernel / "build").exists()

    def firmware_dir(self, relative: str) -> Path:
        return self.paths.firmware / relative

    def module_search_dir(self, kernel: str) -> Path:
        return self.paths.modules / kernel

    def kernel_version(self) -> str:
        return read_text(self.paths.proc / "sys" / "kernel" / "osrelease")


def _phy_order(name: str) -> tuple[int, str]:
    try:
        return (int(name.removeprefix("phy")), name)
    except ValueError:
        return (10**6, name)
