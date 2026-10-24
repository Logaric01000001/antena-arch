"""Modelos de datos compartidos por detección, diagnóstico y presentación."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DeviceStatus(str, Enum):
    READY = "ready"
    NEEDS_SETUP = "needs_setup"
    NEEDS_ATTENTION = "needs_attention"
    UNSUPPORTED = "unsupported"
    BUSY = "busy"


class UsbStage(str, Enum):
    STORAGE = "storage"
    TRANSITIONAL = "transitional"
    OPERATIONAL = "operational"
    UNKNOWN = "unknown"


class Confidence(str, Enum):
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    WEAK = "weak"
    NONE = "none"


@dataclass(frozen=True)
class UsbRecord:
    """Un dispositivo USB tal como lo describe sysfs."""

    path_name: str
    vid: str
    pid: str
    product: str = ""
    manufacturer: str = ""
    serial: str = ""
    device_class: int = 0
    interface_classes: tuple[tuple[int, int, int], ...] = ()
    net_names: tuple[str, ...] = ()
    driver_modules: tuple[str, ...] = ()
    speed: str = ""
    busnum: str = ""
    devnum: str = ""
    modalias: str = ""

    @property
    def usb_id(self) -> str:
        return f"{self.vid}:{self.pid}".lower()

    @property
    def is_storage(self) -> bool:
        if self.device_class == 8:
            return True
        return any(cls == 8 for cls, _, _ in self.interface_classes)

    @property
    def display_name(self) -> str:
        if self.product:
            return self.product
        if self.manufacturer:
            return f"{self.manufacturer} {self.usb_id}"
        return self.usb_id.upper()


@dataclass(frozen=True)
class RfkillState:
    index: int
    kind: str
    name: str
    soft_blocked: bool
    hard_blocked: bool


@dataclass(frozen=True)
class WifiInterface:
    name: str
    phy: str = ""
    mac: str = ""
    if_type: str = ""
    channel: int | None = None
    freq_mhz: int | None = None
    nm_state: str = ""
    connected: bool = False
    managed: bool = True
    rfkill: RfkillState | None = None
    supported_modes: tuple[str, ...] = ()
    bands: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        return bool(self.rfkill and (self.rfkill.soft_blocked or self.rfkill.hard_blocked))


@dataclass(frozen=True)
class DkmsStatus:
    package: str
    version: str
    kernel: str
    arch: str
    state: str


@dataclass(frozen=True)
class DriverState:
    module: str = ""
    loaded: bool = False
    module_version: str = ""
    module_path: str = ""
    package: str = ""
    package_version: str = ""
    dkms: tuple[DkmsStatus, ...] = ()
    installed_for_running_kernel: bool = False
    headers_ok: bool = False
    headers_package: str = ""
    candidates: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    @property
    def dkms_state(self) -> str:
        for item in self.dkms:
            if item.state == "installed":
                return "installed"
        for item in self.dkms:
            if item.state in {"built", "built (no install)"}:
                return "built"
        for item in self.dkms:
            if item.state.startswith("build"):
                return "failed"
        return "absent" if not self.dkms else self.dkms[0].state


@dataclass
class DeviceInfo:
    id: str
    kind: str  # "usb" | "pci"
    name: str
    vendor: str = ""
    family: str = ""
    usb: UsbRecord | None = None
    iface: WifiInterface | None = None
    usb_stage: UsbStage = UsbStage.UNKNOWN
    driver: DriverState = field(default_factory=DriverState)
    recipe_id: str | None = None
    confidence: Confidence = Confidence.NONE
    status: DeviceStatus = DeviceStatus.UNSUPPORTED
    reasons: tuple[str, ...] = ()
    capabilities_advertised: tuple[str, ...] = ()
    capabilities_verified: tuple[str, ...] = ()
    internal: bool = False

    @property
    def usb_id(self) -> str:
        return self.usb.usb_id if self.usb else ""

    @property
    def interface_name(self) -> str:
        return self.iface.name if self.iface else ""

    @property
    def is_ready(self) -> bool:
        return self.status is DeviceStatus.READY


@dataclass(frozen=True)
class Environment:
    kernel: str = ""
    distro: str = ""
    dkms_available: bool = False
    usb_modeswitch_available: bool = False
    nm_available: bool = False
    iw_available: bool = False
    tcpdump_available: bool = False
    headers_ok: bool = False
    headers_package: str = ""
    pacman_available: bool = False


@dataclass(frozen=True)
class RepairAction:
    """Una acción concreta y acotada que la interfaz puede ofrecer."""

    id: str
    op: str
    payload: dict[str, Any] = field(default_factory=dict)
    privileged: bool = True


@dataclass
class CheckResult:
    id: str
    status: str  # ok | warning | error | unknown
    title_key: str
    detail: str = ""
    technical: str = ""
    action: RepairAction | None = None
    explain_key: str = ""


@dataclass
class PlanStage:
    key: str
    op: str
    payload: dict[str, Any] = field(default_factory=dict)
    critical: bool = True
    optional_ok: bool = False


@dataclass
class Plan:
    recipe_id: str
    device_id: str
    kind: str  # setup | repair
    stages: list[PlanStage] = field(default_factory=list)
    notes: tuple[str, ...] = ()


@dataclass
class StageEvent:
    index: int
    key: str
    state: str  # pending | running | ok | skipped | failed | cancelled
    message: str = ""
    technical: str = ""


@dataclass
class PlanResult:
    ok: bool
    cancelled: bool = False
    failed_stage: str = ""
    message: str = ""
    technical: str = ""
