"""Motor de diagnóstico: comprobaciones independientes y acciones acotadas."""

from __future__ import annotations

from antena.constants import ALLOWED_PACMAN_PACKAGES, helper_path
from antena.core.catalog import Recipe, find_recipe
from antena.core.detect import Detector, DetectionResult
from antena.core.models import (
    CheckResult,
    DeviceInfo,
    DeviceStatus,
    RepairAction,
    UsbStage,
)
from antena.core.planner import missing_dependencies


class Diagnostics:
    def __init__(
        self,
        detector: Detector,
        helper_available: bool | None = None,
        helper_installed: bool | None = None,
    ) -> None:
        self.detector = detector
        self.helper_available = (
            bool(helper_path()) if helper_available is None and helper_installed is None
            else (helper_available if helper_available is not None else bool(helper_installed))
        )

    def run(self, device_id: str | None = None) -> tuple[list[CheckResult], DetectionResult]:
        detection = self.detector.detect()
        recipes = self.detector.recipes
        checks: list[CheckResult] = []
        checks.append(self._helper_check())
        checks.append(self._nm_check())
        if detection.errors:
            checks.append(
                CheckResult(
                    id="detection",
                    status="warning",
                    title_key="error.detection",
                    detail="; ".join(detection.errors),
                    explain_key="error.detection",
                )
            )
        target = detection.by_id(device_id) if device_id else self._default_target(detection)
        if target is None:
            checks.append(
                CheckResult(
                    id="no_device",
                    status="warning",
                    title_key="diag.no_device",
                    detail="",
                    explain_key="home.subtitle.empty",
                )
            )
            return checks, detection
        recipe = find_recipe(recipes, target.recipe_id) if target.recipe_id else None
        checks.extend(self._device_checks(target, recipe, detection))
        return checks, detection

    @staticmethod
    def _default_target(detection: DetectionResult) -> DeviceInfo | None:
        # Primero lo que requiere atención, después el adaptador USB externo;
        # el Wi-Fi interno solo se elige si no hay nada más.
        for device in detection.devices:
            if device.status is not DeviceStatus.READY:
                return device
        for device in detection.devices:
            if device.kind == "usb":
                return device
        return detection.devices[0] if detection.devices else None

    # ------------------------------------------------------------------
    def _helper_check(self) -> CheckResult:
        if self.helper_available:
            return CheckResult(
                id="helper",
                status="ok",
                title_key="check.helper.title",
                explain_key="check.helper.detail",
                detail="pkexec + antena-helper",
            )
        return CheckResult(
            id="helper",
            status="warning",
            title_key="check.helper.title",
            explain_key="check.helper.detail",
            detail="antena-helper no encontrado",
        )

    def _nm_check(self) -> CheckResult:
        environment = self.detector.environment()
        if not environment.nm_available:
            return CheckResult(
                id="nm",
                status="error",
                title_key="check.nm.title",
                explain_key="check.nm.detail",
                detail="nmcli no disponible",
            )
        status = self.detector.runner.run(["nmcli", "-t", "-f", "RUNNING", "general"], timeout=10)
        running = status.ok and "running" in status.stdout
        return CheckResult(
            id="nm",
            status="ok" if running else "warning",
            title_key="check.nm.title",
            explain_key="check.nm.detail",
            detail=status.stdout.strip() or status.stderr.strip(),
        )

    def _device_checks(
        self, device: DeviceInfo, recipe: Recipe | None, detection: DetectionResult
    ) -> list[CheckResult]:
        checks: list[CheckResult] = []
        checks.append(
            CheckResult(
                id="device",
                status="ok",
                title_key="check.device.title",
                explain_key="check.device.detail",
                detail=device.usb_id or device.name,
            )
        )
        checks.append(self._identity_check(device, recipe))
        checks.append(self._environment_check(recipe, detection))
        if recipe and recipe.modeswitch:
            checks.append(self._storage_check(device, recipe))
        checks.append(self._driver_installed_check(device, recipe))
        if recipe and not recipe.is_kernel_native:
            checks.append(self._headers_check(device, recipe, detection))
            checks.append(self._dkms_check(device, recipe, detection))
        checks.append(self._firmware_check(device, recipe))
        checks.append(self._driver_loaded_check(device, recipe))
        checks.append(self._interface_check(device, recipe))
        checks.append(self._rfkill_check(device))
        checks.append(self._nm_managed_check(device))
        if device.driver.conflicts:
            checks.append(self._conflict_check(device))
        if recipe and recipe.tested_kernels:
            checks.append(self._kernel_check(device, recipe, detection))
        return checks

    def _identity_check(self, device: DeviceInfo, recipe: Recipe | None) -> CheckResult:
        if recipe is None:
            return CheckResult(
                id="identity",
                status="warning",
                title_key="check.identity.title",
                explain_key="check.identity.detail",
                detail="sin receta verificada",
            )
        return CheckResult(
            id="identity",
            status="ok",
            title_key="check.identity.title",
            explain_key="check.identity.detail",
            detail=f"{recipe.name} · {device.confidence.value}",
        )

    def _environment_check(self, recipe: Recipe | None, detection: DetectionResult) -> CheckResult:
        environment = detection.environment
        missing = missing_dependencies(recipe, environment)
        if not environment.pacman_available:
            return CheckResult(
                id="environment",
                status="warning",
                title_key="check.environment.title",
                explain_key="check.environment.detail",
                detail="pacman no disponible",
            )
        if missing:
            packages = [item for item in missing if item in ALLOWED_PACMAN_PACKAGES]
            return CheckResult(
                id="environment",
                status="error",
                title_key="check.environment.title",
                explain_key="check.environment.detail",
                detail=", ".join(missing),
                action=RepairAction(
                    id="packages",
                    op="install_packages",
                    payload={"packages": packages},
                )
                if packages
                else None,
            )
        return CheckResult(
            id="environment",
            status="ok",
            title_key="check.environment.title",
            explain_key="check.environment.detail",
            detail=f"kernel {environment.kernel}",
        )

    def _storage_check(self, device: DeviceInfo, recipe: Recipe) -> CheckResult:
        if device.usb_stage is UsbStage.STORAGE:
            return CheckResult(
                id="storage",
                status="error",
                title_key="check.storage.title",
                explain_key="check.storage.detail",
                detail=device.usb_id,
                action=RepairAction(
                    id="switch",
                    op="switch_mode",
                    payload={"recipe_id": recipe.id, "usb_path": self._usb_path(device)},
                ),
            )
        return CheckResult(
            id="storage",
            status="ok",
            title_key="check.storage.title",
            explain_key="check.storage.detail",
            detail=device.usb_stage.value,
        )

    def _driver_installed_check(self, device: DeviceInfo, recipe: Recipe | None) -> CheckResult:
        if recipe is None:
            return CheckResult(
                id="driver_installed",
                status="unknown",
                title_key="check.driver_installed.title",
                explain_key="check.driver_installed.detail",
                detail=device.driver.module or "sin datos",
            )
        installed = device.driver.installed_for_running_kernel
        if installed:
            return CheckResult(
                id="driver_installed",
                status="ok",
                title_key="check.driver_installed.title",
                explain_key="check.driver_installed.detail",
                detail=device.driver.module,
            )
        if recipe.is_kernel_native:
            return CheckResult(
                id="driver_installed",
                status="error",
                title_key="check.driver_installed.title",
                explain_key="check.driver_installed.detail",
                detail=f"{recipe.primary_module} no está en este kernel",
            )
        return CheckResult(
            id="driver_installed",
            status="error",
            title_key="check.driver_installed.title",
            explain_key="check.driver_installed.detail",
            detail=device.driver.module or recipe.primary_module,
            action=RepairAction(
                id="install_driver",
                op="install_driver",
                payload={"recipe_id": recipe.id, "usb_path": self._usb_path(device)},
            ),
        )

    def _headers_check(
        self, device: DeviceInfo, recipe: Recipe, detection: DetectionResult
    ) -> CheckResult:
        environment = detection.environment
        if environment.headers_ok:
            return CheckResult(
                id="headers",
                status="ok",
                title_key="check.headers.title",
                explain_key="check.headers.detail",
                detail=environment.headers_package or "headers presentes",
            )
        action = None
        if (
            environment.headers_package
            and environment.headers_package in ALLOWED_PACMAN_PACKAGES
        ):
            action = RepairAction(
                id="headers",
                op="install_packages",
                payload={"packages": [environment.headers_package]},
            )
        return CheckResult(
            id="headers",
            status="warning",
            title_key="check.headers.title",
            explain_key="check.headers.detail",
            detail=environment.headers_package or "kernel personalizado: sin paquete de headers",
            action=action,
        )

    def _dkms_check(
        self, device: DeviceInfo, recipe: Recipe, detection: DetectionResult
    ) -> CheckResult:
        states = device.driver.dkms
        running = detection.environment.kernel
        detail = ", ".join(f"{item.version}@{item.kernel}: {item.state}" for item in states)
        if any(item.state == "installed" and item.kernel == running for item in states):
            return CheckResult(
                id="dkms",
                status="ok",
                title_key="check.dkms.title",
                explain_key="check.dkms.detail",
                detail=detail,
            )
        if states and any(item.state.startswith("build") for item in states):
            return CheckResult(
                id="dkms",
                status="error",
                title_key="check.dkms.title",
                explain_key="check.dkms.detail",
                detail=detail,
                action=RepairAction(
                    id="dkms",
                    op="dkms_rebuild",
                    payload={"recipe_id": recipe.id},
                ),
            )
        if states:
            return CheckResult(
                id="dkms",
                status="warning",
                title_key="check.dkms.title",
                explain_key="check.dkms.detail",
                detail=f"{detail}; kernel en ejecución: {running}",
                action=RepairAction(
                    id="dkms",
                    op="dkms_rebuild",
                    payload={"recipe_id": recipe.id},
                ),
            )
        return CheckResult(
            id="dkms",
            status="warning",
            title_key="check.dkms.title",
            explain_key="check.dkms.detail",
            detail="sin entradas de DKMS",
        )

    def _firmware_check(self, device: DeviceInfo, recipe: Recipe | None) -> CheckResult:
        if recipe is None or not recipe.firmware_dest:
            return CheckResult(
                id="firmware",
                status="unknown",
                title_key="check.firmware.title",
                explain_key="check.firmware.detail",
                detail="sin datos",
            )
        present = self.detector._firmware_present(recipe.firmware_dest)
        if present:
            return CheckResult(
                id="firmware",
                status="ok",
                title_key="check.firmware.title",
                explain_key="check.firmware.detail",
                detail=recipe.firmware_dest,
            )
        action = None
        if recipe.is_kernel_native:
            action = RepairAction(
                id="firmware_pkg",
                op="install_packages",
                payload={"packages": ["linux-firmware"]},
            )
        elif recipe.source:
            action = RepairAction(
                id="firmware_driver",
                op="install_driver",
                payload={"recipe_id": recipe.id, "usb_path": self._usb_path(device)},
            )
        return CheckResult(
            id="firmware",
            status="warning",
            title_key="check.firmware.title",
            explain_key="check.firmware.detail",
            detail=recipe.firmware_dest,
            action=action,
        )

    def _driver_loaded_check(self, device: DeviceInfo, recipe: Recipe | None) -> CheckResult:
        if device.driver.loaded:
            return CheckResult(
                id="driver_loaded",
                status="ok",
                title_key="check.driver_loaded.title",
                explain_key="check.driver_loaded.detail",
                detail=device.driver.module,
            )
        action = None
        if recipe and recipe.modules:
            action = RepairAction(
                id="load",
                op="load_modules",
                payload={"recipe_id": recipe.id, "usb_path": self._usb_path(device)},
            )
        return CheckResult(
            id="driver_loaded",
            status="warning" if device.driver.installed_for_running_kernel else "error",
            title_key="check.driver_loaded.title",
            explain_key="check.driver_loaded.detail",
            detail=device.driver.module or "sin módulo",
            action=action,
        )

    def _interface_check(self, device: DeviceInfo, recipe: Recipe | None) -> CheckResult:
        if device.iface is not None:
            return CheckResult(
                id="interface",
                status="ok",
                title_key="check.interface.title",
                explain_key="check.interface.detail",
                detail=f"{device.iface.name} · {device.iface.phy}",
            )
        action = None
        if device.usb_stage is UsbStage.STORAGE and recipe and recipe.modeswitch:
            action = RepairAction(
                id="switch",
                op="switch_mode",
                payload={"recipe_id": recipe.id, "usb_path": self._usb_path(device)},
            )
        elif recipe:
            action = RepairAction(
                id="load",
                op="load_modules",
                payload={"recipe_id": recipe.id, "usb_path": self._usb_path(device)},
            )
        return CheckResult(
            id="interface",
            status="error",
            title_key="check.interface.title",
            explain_key="check.interface.detail",
            detail=", ".join(device.reasons),
            action=action,
        )

    def _rfkill_check(self, device: DeviceInfo) -> CheckResult:
        if device.iface is None or device.iface.rfkill is None:
            return CheckResult(
                id="rfkill",
                status="unknown",
                title_key="check.rfkill.title",
                explain_key="check.rfkill.detail",
                detail="sin datos de rfkill",
            )
        rfkill = device.iface.rfkill
        if rfkill.hard_blocked:
            return CheckResult(
                id="rfkill",
                status="error",
                title_key="check.rfkill.title",
                explain_key="check.rfkill.detail",
                detail=f"{rfkill.name} · bloqueo físico",
            )
        if rfkill.soft_blocked:
            return CheckResult(
                id="rfkill",
                status="error",
                title_key="check.rfkill.title",
                explain_key="check.rfkill.detail",
                detail=f"{rfkill.name} · bloqueo software",
                action=RepairAction(
                    id="unblock", op="rfkill_unblock", payload={"phy": device.iface.phy}
                ),
            )
        return CheckResult(
            id="rfkill",
            status="ok",
            title_key="check.rfkill.title",
            explain_key="check.rfkill.detail",
            detail=rfkill.name,
        )

    def _nm_managed_check(self, device: DeviceInfo) -> CheckResult:
        if device.iface is None:
            return CheckResult(
                id="nm_managed",
                status="unknown",
                title_key="check.nm_managed.title",
                explain_key="check.nm_managed.detail",
                detail="sin interfaz",
            )
        if device.iface.managed:
            return CheckResult(
                id="nm_managed",
                status="ok",
                title_key="check.nm_managed.title",
                explain_key="check.nm_managed.detail",
                detail=device.iface.nm_state or "gestionada",
            )
        return CheckResult(
            id="nm_managed",
            status="warning",
            title_key="check.nm_managed.title",
            explain_key="check.nm_managed.detail",
            detail=device.iface.nm_state or "unmanaged",
            action=RepairAction(
                id="manage", op="nm_manage", payload={"iface": device.iface.name}
            ),
        )

    def _conflict_check(self, device: DeviceInfo) -> CheckResult:
        return CheckResult(
            id="conflict",
            status="warning",
            title_key="check.conflict.title",
            explain_key="check.conflict.detail",
            detail=", ".join(device.driver.conflicts),
        )

    def _kernel_check(
        self, device: DeviceInfo, recipe: Recipe, detection: DetectionResult
    ) -> CheckResult:
        kernel = detection.environment.kernel
        if kernel in recipe.tested_kernels:
            return CheckResult(
                id="kernel",
                status="ok",
                title_key="check.kernel.title",
                explain_key="check.kernel.detail",
                detail=kernel,
            )
        return CheckResult(
            id="kernel",
            status="warning",
            title_key="check.kernel.title",
            explain_key="check.kernel.detail",
            detail=f"kernel {kernel}; probado en {', '.join(recipe.tested_kernels)}",
        )

    @staticmethod
    def _usb_path(device: DeviceInfo) -> str:
        return device.usb.path_name if device.usb else ""
