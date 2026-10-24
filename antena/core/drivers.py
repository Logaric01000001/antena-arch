"""Inspección de módulos, DKMS, pacman y firmware."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass

from antena.core.models import DkmsStatus, DriverState
from antena.core.runner import Runner
from antena.core.sysfs import Sysfs, read_text


def parse_modules(text: str) -> dict[str, dict[str, str]]:
    modules: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue
        name = fields[0]
        dependencies = fields[3].split(",") if len(fields) > 3 and fields[3] != "-" else []
        modules[name] = {
            "size": fields[1] if len(fields) > 1 else "",
            "refcount": fields[2] if len(fields) > 2 else "",
            "deps": ",".join(dependencies),
            "state": fields[4] if len(fields) > 4 else "Live",
        }
    return modules


def parse_dkms_status(text: str) -> tuple[DkmsStatus, ...]:
    items: list[DkmsStatus] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^(\S+)/(\S+),\s*(\S+),\s*(\S+):\s*(.+)$", line)
        if not match:
            continue
        items.append(
            DkmsStatus(
                package=match.group(1),
                version=match.group(2),
                kernel=match.group(3),
                arch=match.group(4),
                state=match.group(5).strip(),
            )
        )
    return tuple(items)


def parse_pacman_query(text: str) -> tuple[str, str]:
    # "paquete 1.2.3-4"
    parts = text.strip().split()
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return "", ""


def kernel_headers_package(kernel: str) -> str:
    if "cachyos" in kernel:
        return "linux-cachyos-headers"
    if "zen" in kernel:
        return "linux-zen-headers"
    if "lts" in kernel:
        return "linux-lts-headers"
    if "hardened" in kernel:
        return "linux-hardened-headers"
    if "arch" in kernel:
        return "linux-headers"
    # Kernel personalizado: no se instala un paquete de headers que no
    # corresponde. El usuario debe aportar los suyos.
    return ""


@dataclass
class DriverInspector:
    sysfs: Sysfs
    runner: Runner

    def kernel(self) -> str:
        return self.sysfs.kernel_version()

    def loaded_modules(self) -> dict[str, dict[str, str]]:
        return parse_modules(read_text(self.sysfs.paths.proc / "modules"))

    def module_path(self, module: str) -> str:
        if not module:
            return ""
        result = self.runner.run(["modinfo", "-n", module], timeout=10)
        return result.stdout.strip() if result.ok else ""

    def module_version(self, module: str) -> str:
        if not module:
            return ""
        result = self.runner.run(["modinfo", "-F", "version", module], timeout=10)
        return result.stdout.strip() if result.ok else ""

    def module_aliases(self, module: str) -> tuple[str, ...]:
        if not module:
            return ()
        result = self.runner.run(["modinfo", "-F", "alias", module], timeout=10)
        if not result.ok:
            return ()
        return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())

    def alias_candidates(self, modalias: str, kernel: str, wifi_only: bool = True) -> tuple[str, ...]:
        """Módulos que el kernel asociaría a este modalias (lectura de modules.alias)."""
        if not modalias:
            return ()
        alias_file = self.sysfs.paths.modules / kernel / "modules.alias"
        text = read_text(alias_file)
        if not text:
            return ()
        found: list[str] = []
        for line in text.splitlines():
            if not line.startswith("alias "):
                continue
            parts = line.split(None, 2)
            if len(parts) != 3:
                continue
            pattern, module = parts[1], parts[2].strip()
            if fnmatch.fnmatchcase(modalias, pattern):
                if wifi_only and not _looks_like_wifi_module(module):
                    continue
                if module not in found:
                    found.append(module)
        return tuple(found)

    def dkms_status(self, package: str = "") -> tuple[DkmsStatus, ...]:
        args = ["dkms", "status"]
        if package:
            args.append(package)
        result = self.runner.run(args, timeout=20)
        if not result.ok:
            return ()
        return parse_dkms_status(result.stdout)

    def package_version(self, package: str) -> tuple[bool, str]:
        result = self.runner.run(["pacman", "-Q", package], timeout=10)
        if not result.ok:
            return False, ""
        return True, parse_pacman_query(result.stdout)[1]

    def installed_packages(self) -> tuple[str, ...]:
        result = self.runner.run(["pacman", "-Qq"], timeout=20)
        if not result.ok:
            return ()
        return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())

    def headers_ok(self, kernel: str) -> bool:
        return self.sysfs.headers_ok(kernel)

    def headers_package_version(self, package: str) -> str:
        return self.package_version(package)[1]

    def inspect(
        self,
        module: str,
        *,
        package: str = "",
        dkms_package: str = "",
        alternatives: tuple[str, ...] = (),
        conflict_prefixes: tuple[str, ...] = ("aic8800",),
        expected_dkms: str = "",
    ) -> DriverState:
        kernel = self.kernel()
        loaded = self.loaded_modules()
        dkms_items = self.dkms_status(dkms_package) if dkms_package else self.dkms_status()
        pkg_ok, pkg_version = self.package_version(package) if package else (False, "")
        module_path = self.module_path(module) if module else ""
        headers = self.headers_ok(kernel)
        installed_for_kernel = any(
            item.kernel == kernel and item.state == "installed" for item in dkms_items
        )
        if not installed_for_kernel and module_path:
            installed_for_kernel = True
        candidates: list[str] = []
        for item in (module, *alternatives):
            if item and item not in candidates:
                candidates.append(item)
        conflicts: list[str] = []
        for pkg in self.installed_packages():
            lowered = pkg.lower()
            if any(lowered.startswith(prefix) for prefix in conflict_prefixes):
                if pkg in {package, expected_dkms}:
                    continue
                conflicts.append(f"{pkg} {self.package_version(pkg)[1]}".strip())
        return DriverState(
            module=module,
            loaded=module in loaded,
            module_version=self.module_version(module) if module else "",
            module_path=module_path,
            package=package if pkg_ok else "",
            package_version=pkg_version,
            dkms=dkms_items,
            installed_for_running_kernel=installed_for_kernel,
            headers_ok=headers,
            headers_package=kernel_headers_package(kernel),
            candidates=tuple(candidates),
            conflicts=tuple(conflicts),
        )

    def firmware_present(self, relative: str) -> bool:
        if not relative:
            return True
        return self.sysfs.firmware_dir(relative).is_dir()

    def module_file_present(self, module: str, kernel: str) -> bool:
        base = self.sysfs.module_search_dir(kernel)
        if not base.is_dir():
            return False
        for pattern in (f"**/{module}.ko", f"**/{module}.ko.xz", f"**/{module}.ko.zst"):
            if any(base.glob(pattern)):
                return True
        return False


def _looks_like_wifi_module(module: str) -> bool:
    markers = (
        "cfg80211",
        "mac80211",
        "rtl8",
        "rtw8",
        "rt2800",
        "mt76",
        "mt7601",
        "ath9k",
        "ath10k",
        "ath11k",
        "ath12k",
        "iwlwifi",
        "aic",
    )
    return any(marker in module for marker in markers)
