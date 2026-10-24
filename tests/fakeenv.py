"""Entorno sysfs simulado para pruebas reproducibles (sin hardware real)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from antena.core.runner import CommandResult
from antena.core.sysfs import SystemPaths

REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO / "antena" / "catalog"
KERNEL = "7.2.11-arch1-1"


class FakeRunner:
    def __init__(self) -> None:
        self.responses: list[tuple[tuple[str, ...], CommandResult]] = []
        self.programs: set[str] = set()
        self.calls: list[tuple[str, ...]] = []

    def set(self, prefix: str | Iterable[str], stdout: str = "", rc: int = 0, stderr: str = "") -> None:
        tokens = tuple(prefix.split()) if isinstance(prefix, str) else tuple(prefix)
        self.responses.append(
            (tokens, CommandResult(tokens, rc, stdout, stderr))
        )

    def run(self, args, timeout: float = 15.0, env=None) -> CommandResult:
        argv = tuple(str(item) for item in args)
        self.calls.append(argv)
        best: tuple[int, CommandResult] | None = None
        for prefix, response in self.responses:
            if len(argv) >= len(prefix) and argv[: len(prefix)] == prefix:
                if best is None or len(prefix) > best[0]:
                    best = (len(prefix), response)
        if best is not None:
            return best[1]
        return CommandResult(argv, 127, "", f"comando no simulado: {' '.join(argv)}")

    def which(self, program: str) -> str | None:
        return f"/usr/bin/{program}" if program in self.programs else None


@dataclass
class FakeWifi:
    name: str
    phy: str
    driver: str
    mac: str
    nm_state: str = "disconnected"
    connection: str = ""
    usb: bool = False


class FakeEnvironment:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.sys = self.root / "sys"
        self.proc = self.root / "proc"
        self.modules_root = self.root / "lib" / "modules" / KERNEL
        self.firmware_root = self.root / "lib" / "firmware"
        self.paths = SystemPaths(
            sys=self.sys,
            proc=self.proc,
            modules=self.root / "lib" / "modules",
            firmware=self.firmware_root,
            os_release=self.root / "etc" / "os-release",
            source_catalog=CATALOG,
        )
        self.runner = FakeRunner()
        self.runner.programs = {"dkms", "usb_modeswitch", "nmcli", "iw", "pacman", "tcpdump"}
        self.wifi: dict[str, FakeWifi] = {}
        self.module_info: dict[str, dict[str, object]] = {}
        self.dkms_entries: list[tuple[str, str, str, str, str]] = []
        self.packages: dict[str, str] = {
            "dkms": "3.2.1-1",
            "usb_modeswitch": "2.6.2-1",
            "linux-headers": "7.2.11.arch1-1",
            "linux-firmware": "20260101-1",
            "iw": "6.17-1",
            "tcpdump": "4.99.5-1",
        }
        self.extra_aliases: list[str] = []
        self.headers = True
        self.scan_networks: list[str] = [
            "IN-USE:SSID:SIGNAL:FREQ:SECURITY",
            ":TestLab:88:2437 MHz:WPA2",
            ":TestLab-5G:61:5180 MHz:WPA2",
        ]
        self._init_tree()

    # ------------------------------------------------------------------
    def _init_tree(self) -> None:
        for directory in (
            self.sys / "bus" / "usb" / "devices",
            self.sys / "bus" / "usb" / "drivers",
            self.sys / "class" / "net",
            self.sys / "class" / "ieee80211",
            self.sys / "class" / "rfkill",
            self.sys / "devices",
            self.proc / "sys" / "kernel",
            self.modules_root,
            self.firmware_root,
            self.root / "etc",
        ):
            directory.mkdir(parents=True, exist_ok=True)
        (self.proc / "sys" / "kernel" / "osrelease").write_text(KERNEL + "\n")
        (self.proc / "modules").write_text("")
        (self.root / "etc" / "os-release").write_text(
            'NAME="Arch Linux"\nPRETTY_NAME="Arch Linux"\nID=arch\n'
        )
        if self.headers:
            (self.modules_root / "build").mkdir(exist_ok=True)
        (self.modules_root / "modules.alias").write_text(
            "alias usb:vA69Cp8D83d*dc*dsc*dp*ic*isc*ip*in* aic8800_fdrv\n"
            "alias usb:vA69Cp8D80d*dc*dsc*dp*ic*isc*ip*in* aic8800_fdrv\n"
        )

    # -- dispositivos ---------------------------------------------------
    def add_aic(
        self,
        *,
        vid: str = "a69c",
        pid: str = "8d83",
        product: str = "AIC 8800D80",
        manufacturer: str = "AICSemi",
        storage: bool = False,
        interface: str | None = "wlan1",
        driver: str = "aic8800_fdrv",
        driver_installed: bool = True,
        loaded: bool = True,
        dkms_state: str = "installed",
        dkms_kernel: str = KERNEL,
        firmware: bool = True,
        nm_state: str = "disconnected",
    ) -> None:
        if storage:
            interface = None
            driver = ""
            # El modo de almacenamiento real usa 1111:1111 y el producto 88M80.
            if vid == "a69c" and pid == "8d83":
                vid, pid = "1111", "1111"
                product, manufacturer = "88M80", "AIC"
        self.add_usb(
            path="1-1",
            vid=vid,
            pid=pid,
            product=product,
            manufacturer=manufacturer,
            device_class=8 if storage else 0,
            interface_class=8 if storage else 255,
            interface_name=interface,
            driver=driver,
            phy="phy1" if interface else "",
            nm_state=nm_state,
        )
        if driver:
            self.add_module(
                driver,
                version="6.4.3.0" if driver == "aic8800_fdrv" else "",
                installed=driver_installed,
                aliases=[f"usb:vA69Cp{pid.upper()}d*dc*dsc*dp*ic*isc*ip*in*"],
            )
            if driver == "aic8800_fdrv":
                self.add_module("aic_load_fw", version="", installed=driver_installed)
        if driver_installed and driver:
            self.packages["aic8800-fdrv-dkms"] = "6.4.3.0-8"
            if dkms_state:
                self.dkms_entries.append(
                    ("aic8800-fdrv-dkms", "6.4.3.0", dkms_kernel, "x86_64", dkms_state)
                )
            if firmware:
                (self.firmware_root / "aic8800D80").mkdir(parents=True, exist_ok=True)
        (self.proc / "modules").write_text(self._modules_text())
        self.refresh()

    def add_kernel_usb(
        self,
        *,
        path: str,
        vid: str,
        pid: str,
        driver: str,
        product: str,
        interface: str,
        phy: str,
        manufacturer: str = "MediaTek",
        interface_class: int = 255,
        nm_state: str = "disconnected",
    ) -> None:
        self.add_usb(
            path=path,
            vid=vid,
            pid=pid,
            product=product,
            manufacturer=manufacturer,
            device_class=0,
            interface_class=interface_class,
            interface_name=interface,
            driver=driver,
            phy=phy,
            nm_state=nm_state,
        )
        version = self._module_version()
        self.add_module(driver, version=version, installed=True)
        self.extra_aliases.append(
            f"alias usb:v{vid.upper()}p{pid.upper()}d*dc*dsc*dp*ic*isc*ip*in* {driver}"
        )
        self._write_aliases()
        (self.proc / "modules").write_text(self._modules_text())
        self.refresh()

    def add_usb(
        self,
        *,
        path: str,
        vid: str,
        pid: str,
        product: str,
        manufacturer: str,
        device_class: int,
        interface_class: int,
        interface_name: str | None,
        driver: str,
        phy: str,
        nm_state: str = "disconnected",
    ) -> None:
        device = self.sys / "bus" / "usb" / "devices" / path
        device.mkdir(parents=True, exist_ok=True)
        for name, value in (
            ("idVendor", vid),
            ("idProduct", pid),
            ("product", product),
            ("manufacturer", manufacturer),
            ("serial", "20220103"),
            ("bDeviceClass", f"{device_class:02x}"),
            ("speed", "480"),
            ("busnum", "1"),
            ("devnum", "6"),
            ("modalias", f"usb:v{vid.upper()}p{pid.upper()}d0100dc00dsc00dp00ic{interface_class:02x}isc00ip00in00"),
        ):
            (device / name).write_text(value + "\n")
        interface = device / f"{path}:1.0"
        interface.mkdir(exist_ok=True)
        (interface / "bInterfaceClass").write_text(f"{interface_class:02x}\n")
        (interface / "bInterfaceSubClass").write_text("00\n")
        (interface / "bInterfaceProtocol").write_text("00\n")
        if driver:
            driver_dir = self.sys / "bus" / "usb" / "drivers" / driver
            driver_dir.mkdir(parents=True, exist_ok=True)
            try:
                (interface / "driver").symlink_to(driver_dir)
            except FileExistsError:
                pass
        if interface_name:
            net = device / "net"
            net.mkdir(exist_ok=True)
            try:
                (net / interface_name).symlink_to(self.sys / "class" / "net" / interface_name)
            except FileExistsError:
                pass
            self._add_wifi(interface_name, phy, driver or "usb", nm_state, usb=True, device=device)
            self._add_rfkill(phy)

    def add_internal(
        self,
        *,
        name: str = "wlan0",
        driver: str = "rtw88_8821ce",
        phy: str = "phy0",
        nm_state: str = "connected",
        connection: str = "Casa",
        pci_id: str = "10ec:c821",
    ) -> None:
        pci = self.sys / "devices" / "pci0000:00" / "0000:01:00.0"
        pci.mkdir(parents=True, exist_ok=True)
        (pci / "uevent").write_text(f"PCI_ID={pci_id}\n")
        (pci / "vendor").write_text("0x10ec\n")
        (pci / "device").write_text("0xc821\n")
        driver_dir = self.sys / "bus" / "pci" / "drivers" / driver
        driver_dir.mkdir(parents=True, exist_ok=True)
        try:
            (pci / "driver").symlink_to(driver_dir)
        except FileExistsError:
            pass
        self._add_wifi(name, phy, driver, nm_state, usb=False, device=pci, connection=connection)
        self.add_module(driver, version=self._module_version(), installed=True)
        self._add_rfkill(phy)
        (self.proc / "modules").write_text(self._modules_text())
        self.refresh()

    def _add_wifi(
        self,
        name: str,
        phy: str,
        driver: str,
        nm_state: str,
        *,
        usb: bool,
        device: Path,
        connection: str = "",
    ) -> None:
        net = self.sys / "class" / "net" / name
        net.mkdir(parents=True, exist_ok=True)
        (net / "address").write_text("02:00:00:00:00:01\n")
        (net / "type").write_text("1\n")
        try:
            (net / "device").symlink_to(device)
        except FileExistsError:
            pass
        phy_dir = self.sys / "class" / "ieee80211" / phy
        phy_dir.mkdir(parents=True, exist_ok=True)
        try:
            (phy_dir / "device").symlink_to(device)
        except FileExistsError:
            pass
        try:
            (net / "phy80211").symlink_to(phy_dir)
        except FileExistsError:
            pass
        self.wifi[name] = FakeWifi(
            name=name, phy=phy, driver=driver, mac="02:00:00:00:00:01",
            nm_state=nm_state, connection=connection, usb=usb,
        )

    def _add_rfkill(self, phy: str, *, soft: bool = False, hard: bool = False) -> None:
        index = len(list((self.sys / "class" / "rfkill").glob("rfkill*")))
        entry = self.sys / "class" / "rfkill" / f"rfkill{index}"
        entry.mkdir(exist_ok=True)
        (entry / "type").write_text("wlan\n")
        (entry / "name").write_text(phy + "\n")
        (entry / "soft").write_text(("1" if soft else "0") + "\n")
        (entry / "hard").write_text(("1" if hard else "0") + "\n")

    # -- módulos y paquetes --------------------------------------------
    def add_module(
        self,
        module: str,
        *,
        version: str = "",
        installed: bool = True,
        loaded: bool | None = None,
        aliases: list[str] | None = None,
    ) -> None:
        if loaded is None:
            loaded = installed
        self.module_info[module] = {
            "version": version,
            "installed": installed,
            "loaded": loaded,
            "aliases": aliases or [],
        }
        self._write_aliases()
        (self.proc / "modules").write_text(self._modules_text())
        self.refresh()

    def set_loaded(self, module: str, loaded: bool) -> None:
        if module in self.module_info:
            self.module_info[module]["loaded"] = loaded
            (self.proc / "modules").write_text(self._modules_text())
            self.refresh()

    def _module_version(self) -> str:
        return "6.1"

    def _modules_text(self) -> str:
        lines = []
        for name, info in self.module_info.items():
            if info.get("loaded"):
                lines.append(f"{name} 16384 0 - Live 0x0000000000000000")
        return "\n".join(lines) + ("\n" if lines else "")

    def _write_aliases(self) -> None:
        base = (
            "alias usb:vA69Cp8D83d*dc*dsc*dp*ic*isc*ip*in* aic8800_fdrv\n"
            "alias usb:vA69Cp8D80d*dc*dsc*dp*ic*isc*ip*in* aic8800_fdrv\n"
        )
        (self.modules_root / "modules.alias").write_text(base + "\n".join(self.extra_aliases) + "\n")

    def set_dkms(self, entries: list[tuple[str, str, str, str, str]]) -> None:
        self.dkms_entries = list(entries)
        self.refresh()

    def set_package(self, name: str, version: str | None) -> None:
        if version is None:
            self.packages.pop(name, None)
        else:
            self.packages[name] = version
        self.refresh()

    def set_headers(self, present: bool) -> None:
        self.headers = present
        build = self.modules_root / "build"
        if present:
            build.mkdir(parents=True, exist_ok=True)
        elif build.exists():
            shutil.rmtree(build)
        self.refresh()

    # -- red ------------------------------------------------------------
    def set_nm(self, name: str, state: str, connection: str = "") -> None:
        if name in self.wifi:
            self.wifi[name].nm_state = state
            self.wifi[name].connection = connection
        self.refresh()

    def set_scan_networks(self, lines: list[str]) -> None:
        self.scan_networks = lines
        self.refresh()

    def refresh(self) -> None:
        runner = self.runner
        runner.responses.clear()

        status_lines = []
        for name, wifi in self.wifi.items():
            status_lines.append(f"{name}:wifi:{wifi.nm_state}:{wifi.connection}")
        runner.set("nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status", "\n".join(status_lines) + "\n")
        runner.set("nmcli -t -f RUNNING general", "running\n")
        for name, wifi in self.wifi.items():
            runner.set(
                f"nmcli -t -f GENERAL.DEVICE,GENERAL.TYPE,GENERAL.STATE,GENERAL.CONNECTION,GENERAL.HWADDR device show {name}",
                f"GENERAL.DEVICE:{name}\nGENERAL.TYPE:wifi\n"
                f"GENERAL.STATE:{wifi.nm_state}\nGENERAL.CONNECTION:{wifi.connection}\n"
                f"GENERAL.HWADDR:{wifi.mac}\n",
            )
            runner.set(f"nmcli device set {name} managed yes", "")
            runner.set(
                f"nmcli -t -f GENERAL.STATE device show {name}",
                f"GENERAL.STATE:{wifi.nm_state}\n",
            )

        iw_lines = []
        for name, wifi in self.wifi.items():
            iw_lines.append(
                f"phy#{wifi.phy[-1]}\n\tInterface {name}\n\t\taddr {wifi.mac}\n"
                f"\t\ttype managed\n\t\tchannel 6 (2437 MHz), width: 20 MHz\n"
            )
        runner.set("iw dev", "\n".join(iw_lines))
        for phy in {wifi.phy for wifi in self.wifi.values()}:
            runner.set(
                f"iw phy {phy} info",
                "Wiphy " + phy + "\n"
                "\tSupported interface modes:\n\t\t * managed\n\t\t * AP\n\t\t * monitor\n"
                "\t\t * mesh point\n"
                "\tBand 1:\n\t\tCapabilities: 0x1\n"
                "\tBand 2:\n\t\tCapabilities: 0x1\n",
            )

        for module, info in self.module_info.items():
            if info.get("installed"):
                path = f"/lib/modules/{KERNEL}/updates/dkms/{module}.ko.zst"
                runner.set(f"modinfo -n {module}", path + "\n")
                if info.get("version"):
                    runner.set(f"modinfo -F version {module}", str(info["version"]) + "\n")
                aliases = info.get("aliases") or []
                runner.set(f"modinfo -F alias {module}", "\n".join(aliases) + ("\n" if aliases else ""))
            else:
                runner.set(f"modinfo -n {module}", "", rc=1)
                runner.set(f"modinfo -F version {module}", "", rc=1)
                runner.set(f"modinfo -F alias {module}", "", rc=1)

        if self.dkms_entries:
            dkms_lines = [
                f"{pkg}/{version}, {kernel}, {arch}: {state}"
                for pkg, version, kernel, arch, state in self.dkms_entries
            ]
            runner.set("dkms status", "\n".join(dkms_lines) + "\n")
            for pkg in {item[0] for item in self.dkms_entries}:
                lines = [line for line in dkms_lines if line.startswith(pkg + "/")]
                runner.set(f"dkms status {pkg}", "\n".join(lines) + "\n")
        else:
            runner.set("dkms status", "")
        for pkg in {item[0] for item in self.dkms_entries}:
            if not any(prefix == ("dkms", "status", pkg) for prefix, _ in runner.responses):
                runner.set(f"dkms status {pkg}", "")

        runner.set("pacman -Qq", "\n".join(sorted(self.packages)) + "\n")
        for pkg, version in self.packages.items():
            if pkg != "linux-headers" or self.headers:
                runner.set(f"pacman -Q {pkg}", f"{pkg} {version}\n")
            else:
                runner.set(f"pacman -Q {pkg}", "", rc=1)
        runner.set("udevadm control --reload-rules", "")
        runner.set("nmcli device wifi rescan", "")
        runner.set("nmcli -t -f IN-USE,SSID,SIGNAL,FREQ,SECURITY device wifi list", "\n".join(self.scan_networks) + "\n")
        runner.set("pacman -S --needed --noconfirm", "")
        runner.set("modprobe", "")
        runner.set("depmod", "")

    # -- utilidades -----------------------------------------------------
    def detector(self):
        from antena.core.detect import Detector

        return Detector(paths=self.paths, runner=self.runner)

    def write_pcap(self, path: Path, beacons: int = 2, others: int = 1) -> None:
        import struct

        header = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 127)
        frames = bytearray(header)
        for index in range(beacons + others):
            frame_type = 0x80 if index < beacons else 0x40
            radiotap = struct.pack("<BBHI", 0, 0, 8, 0)
            frame = bytes([frame_type, 0x00]) + b"\x00" * 22
            payload = radiotap + frame
            frames += struct.pack("<IIII", 0, 0, len(payload), len(payload)) + payload
        path.write_bytes(bytes(frames))


def make_env(tmp_path: Path) -> FakeEnvironment:
    return FakeEnvironment(tmp_path)
