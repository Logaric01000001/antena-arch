"""Integración con NetworkManager, iw y rfkill (siempre en modo lectura)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from antena.core.models import RfkillState, WifiInterface
from antena.core.runner import Runner
from antena.core.sysfs import Sysfs


def split_nmcli(line: str) -> list[str]:
    """Divide una línea de nmcli -t respetando los ':' escapados."""
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields


@dataclass(frozen=True)
class Network:
    ssid: str
    signal: int
    freq_mhz: int
    security: str
    in_use: bool = False

    @property
    def band(self) -> str:
        if self.freq_mhz >= 5925:
            return "6ghz"
        if self.freq_mhz >= 4900:
            return "5ghz"
        if self.freq_mhz >= 2400:
            return "2.4ghz"
        return "unknown"


class NetworkTools:
    def __init__(self, sysfs: Sysfs, runner: Runner) -> None:
        self.sysfs = sysfs
        self.runner = runner

    def nm_available(self) -> bool:
        return self.runner.which("nmcli") is not None

    def nm_states(self) -> dict[str, dict[str, str]]:
        result = self.runner.run(
            ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"],
            timeout=10,
        )
        if not result.ok:
            return {}
        states: dict[str, dict[str, str]] = {}
        for line in result.stdout.splitlines():
            fields = split_nmcli(line)
            if len(fields) < 4:
                continue
            device, dev_type, state, connection = fields[:4]
            states[device] = {
                "type": dev_type,
                "state": state,
                "connection": connection,
            }
        return states

    def device_state(self, interface: str) -> dict[str, str]:
        return self.nm_states().get(interface, {})

    def iw_devices(self) -> dict[str, dict[str, str]]:
        result = self.runner.run(["iw", "dev"], timeout=10)
        devices: dict[str, dict[str, str]] = {}
        if not result.ok:
            return devices
        current: dict[str, str] | None = None
        for raw in result.stdout.splitlines():
            line = raw.strip()
            if line.startswith("Interface "):
                current = {"phy": "", "type": "", "addr": "", "ssid": ""}
                devices[line.split(maxsplit=1)[1]] = current
                continue
            if current is None:
                continue
            if line.startswith("phy#"):
                current["phy"] = line
            elif line.startswith("addr "):
                current["addr"] = line.split(maxsplit=1)[1]
            elif line.startswith("ssid "):
                current["ssid"] = line.split(maxsplit=1)[1]
            elif line.startswith("type "):
                current["type"] = line.split(maxsplit=1)[1]
            elif line.startswith("channel "):
                match = re.search(r"channel\s+(\d+)\s+\((\d+) MHz\)", line)
                if match:
                    current["channel"] = match.group(1)
                    current["freq"] = match.group(2)
        return devices

    def iw_phy_info(self, phy: str) -> dict[str, object]:
        result = self.runner.run(["iw", "phy", phy, "info"], timeout=10)
        info: dict[str, object] = {"modes": [], "bands": []}
        if not result.ok:
            return info
        modes: list[str] = []
        bands: list[str] = []
        in_modes = False
        for raw in result.stdout.splitlines():
            line = raw.strip()
            if line.startswith("Supported interface modes:"):
                in_modes = True
                continue
            if in_modes:
                if line.startswith("* "):
                    modes.append(line[2:].strip())
                    continue
                in_modes = False
            if line.startswith("Band ") and ":" in line:
                bands.append(line.rstrip(":").strip())
        info["modes"] = tuple(modes)
        info["bands"] = tuple(bands)
        return info

    def wifi_interface(self, name: str, rfkill: list[RfkillState] | None = None) -> WifiInterface | None:
        if not self.sysfs.net_is_wireless(name):
            return None
        phy = self.sysfs.net_phy(name)
        state = self.device_state(name)
        iw_info = self.iw_devices().get(name, {})
        phy_info = self.iw_phy_info(phy) if phy else {}
        rfkill_match = None
        for entry in rfkill if rfkill is not None else self.sysfs.rfkill():
            if entry.kind == "wlan" and entry.name == phy:
                rfkill_match = entry
                break
        channel = None
        freq = None
        try:
            channel = int(iw_info["channel"]) if "channel" in iw_info else None
        except ValueError:
            channel = None
        try:
            freq = int(iw_info["freq"]) if "freq" in iw_info else None
        except ValueError:
            freq = None
        return WifiInterface(
            name=name,
            phy=phy,
            mac=self.sysfs.net_mac(name),
            if_type=iw_info.get("type", ""),
            channel=channel,
            freq_mhz=freq,
            nm_state=state.get("state", ""),
            connected=state.get("state") == "connected",
            managed=state.get("state", "") != "unmanaged",
            rfkill=rfkill_match,
            supported_modes=tuple(phy_info.get("modes", ())),
            bands=tuple(phy_info.get("bands", ())),
        )

    def scan(self, interface: str, timeout: float = 25.0) -> tuple[bool, list[Network], str]:
        """Escanea con NetworkManager. Devuelve (ok, redes, detalle técnico)."""
        if not self.nm_available():
            return False, [], "nmcli no está instalado"
        rescan = self.runner.run(["nmcli", "device", "wifi", "rescan", "ifname", interface], timeout=10)
        listing = self.runner.run(
            [
                "nmcli",
                "-t",
                "-f",
                "IN-USE,SSID,SIGNAL,FREQ,SECURITY",
                "device",
                "wifi",
                "list",
                "ifname",
                interface,
            ],
            timeout=timeout,
        )
        if not listing.ok:
            detail = (listing.stderr or rescan.stderr or "nmcli falló").strip()
            return False, [], detail
        networks: list[Network] = []
        seen: set[str] = set()
        for line in listing.stdout.splitlines():
            fields = split_nmcli(line)
            if len(fields) < 5:
                continue
            in_use, ssid, signal, freq, security = fields[:5]
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            try:
                signal_value = int(signal)
            except ValueError:
                signal_value = 0
            freq_value = 0
            match = re.match(r"(\d+)", freq)
            if match:
                freq_value = int(match.group(1))
            networks.append(
                Network(
                    ssid=ssid,
                    signal=signal_value,
                    freq_mhz=freq_value,
                    security=security,
                    in_use=bool(in_use.strip()),
                )
            )
        return True, networks, f"nmcli: {len(networks)} redes"
