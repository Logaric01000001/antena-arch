"""Ejecutor de planes con verificación real de cada etapa."""

from __future__ import annotations

import time
from threading import Event
from typing import Callable

from antena.core.detect import Detector
from antena.core.models import (
    DeviceInfo,
    DeviceStatus,
    Plan,
    PlanResult,
    StageEvent,
    UsbStage,
)
from antena.core.privileged import PrivilegedClient, PrivilegedResult
from antena.core.runner import CommandRunner
from antena.priv.state import files_for, load_state

EventCallback = Callable[[StageEvent], None]


def _packages_installed(packages: list[str]) -> bool:
    runner = CommandRunner()
    return all(runner.run(["pacman", "-Q", item], timeout=10).ok for item in packages)


def _persistence_installed(recipe_id: str) -> bool:
    from pathlib import Path

    state = load_state()
    paths = files_for(state, f"persistence:{recipe_id}")
    return bool(paths) and all(Path(path).exists() for path in paths)


class PlanExecutor:
    def __init__(
        self,
        detector: Detector,
        client: PrivilegedClient,
        on_event: EventCallback | None = None,
    ) -> None:
        self.detector = detector
        self.client = client
        self.on_event = on_event

    def _emit(self, index: int, key: str, state: str, message: str = "", technical: str = "") -> None:
        if self.on_event:
            self.on_event(
                StageEvent(index=index, key=key, state=state, message=message, technical=technical)
            )

    def execute(self, plan: Plan, cancel: Event | None = None) -> PlanResult:
        cancel = cancel or Event()
        self._plan_device_id = plan.device_id
        total = len(plan.stages)
        last_technical = ""
        for index, stage in enumerate(plan.stages):
            if cancel.is_set():
                self._emit(index, stage.key, "cancelled")
                return PlanResult(ok=False, cancelled=True, failed_stage=stage.key)
            self._emit(index, stage.key, "running")
            try:
                outcome = self._run_stage(stage.op, stage.payload, cancel)
            except RuntimeError as exc:
                outcome = PrivilegedResult(ok=False, code="stage_error", message=str(exc))
            if outcome.cancelled:
                self._emit(index, stage.key, "cancelled")
                return PlanResult(ok=False, cancelled=True, failed_stage=stage.key)
            if outcome.code == "skipped":
                self._emit(index, stage.key, "skipped", outcome.message)
                continue
            if not outcome.ok:
                self._emit(
                    index,
                    stage.key,
                    "failed",
                    outcome.message or "La etapa falló.",
                    outcome.technical,
                )
                return PlanResult(
                    ok=False,
                    failed_stage=stage.key,
                    message=outcome.message,
                    technical=outcome.technical,
                )
            self._emit(
                index,
                stage.key,
                "ok",
                outcome.message,
                outcome.technical,
            )
            last_technical = outcome.technical
            if index + 1 < total:
                time.sleep(0.15)
        return PlanResult(ok=True, technical=last_technical)

    # ------------------------------------------------------------------
    def _run_stage(
        self, op: str, payload: dict, cancel: Event
    ) -> PrivilegedResult:
        if op.startswith("priv:"):
            operation = op.split(":", 1)[1]
            skipped = self._should_skip(operation, payload)
            if skipped is not None:
                return PrivilegedResult(ok=True, code="skipped", message=skipped)
            return self.client.call(operation, payload, cancel=cancel)
        return self._local(op, payload, cancel)

    def _current(self, device_id: str) -> tuple[DeviceInfo | None, object]:
        detection = self.detector.detect()
        return detection.by_id(device_id), detection

    def _device(self, plan_device: str) -> DeviceInfo | None:
        # El id se conserva en payload cuando hace falta; el ejecutor guarda el
        # plan actual para verificaciones locales.
        return self._current(plan_device)[0]

    def _should_skip(self, operation: str, payload: dict) -> str | None:
        device_id = getattr(self, "_plan_device_id", "")
        if not device_id:
            return None
        device = self._device(device_id)
        if operation == "switch_mode" and device is not None:
            if device.usb_stage in (UsbStage.OPERATIONAL, UsbStage.TRANSITIONAL):
                return "El adaptador ya está en modo operativo."
        if operation == "install_driver" and device is not None:
            if device.driver.installed_for_running_kernel:
                return "El controlador ya está instalado."
        if operation == "load_modules" and device is not None:
            if device.driver.loaded:
                return "Los módulos ya están cargados."
        if operation == "install_packages":
            packages = payload.get("packages", [])
            if isinstance(packages, list) and packages and _packages_installed(packages):
                return "Los componentes ya están instalados."
        if operation == "install_persistence":
            recipe_id = payload.get("recipe_id", "")
            if recipe_id and _persistence_installed(str(recipe_id)):
                return "La persistencia ya está instalada."
        if operation == "rfkill_unblock" and device is not None:
            if device.iface and not device.iface.blocked:
                return "La radio ya está desbloqueada."
        if operation == "nm_manage" and device is not None:
            if device.iface and device.iface.managed:
                return "NetworkManager ya gestiona la interfaz."
        return None

    # -- etapas locales -------------------------------------------------
    def _local(self, op: str, payload: dict, cancel: Event) -> PrivilegedResult:
        if op == "local:verify_environment":
            return self._verify_environment()
        if op == "local:verify_interface":
            return self._verify_interface(payload, cancel)
        if op == "local:scan":
            return self._scan()
        if op == "local:verify_ready":
            return self._verify_ready()
        return PrivilegedResult(ok=False, code="unknown_stage", message=f"Etapa desconocida: {op}")

    def _verify_environment(self) -> PrivilegedResult:
        environment = self.detector.environment()
        if not environment.kernel:
            return PrivilegedResult(ok=False, code="no_kernel", message="No se pudo leer el kernel.")
        technical = (
            f"kernel={environment.kernel}; headers={environment.headers_ok}; "
            f"dkms={environment.dkms_available}; usb_modeswitch={environment.usb_modeswitch_available}"
        )
        return PrivilegedResult(ok=True, message="Entorno comprobado.", technical=technical)

    def _verify_interface(self, payload: dict, cancel: Event) -> PrivilegedResult:
        timeout = payload.get("timeout", 20)
        try:
            limit = float(timeout)
        except (TypeError, ValueError):
            limit = 20.0
        device_id = getattr(self, "_plan_device_id", "")
        deadline = time.monotonic() + limit
        device = None
        while True:
            if cancel.is_set():
                return PrivilegedResult(ok=False, cancelled=True, code="cancelled")
            device = self._device(device_id)
            if device is not None and device.iface is not None:
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(0.5)
        if device is None:
            return PrivilegedResult(
                ok=False, code="device_missing", message="El adaptador ya no está conectado."
            )
        if device.iface is None:
            return PrivilegedResult(
                ok=False,
                code="no_interface",
                message="El controlador no creó una interfaz Wi-Fi.",
                technical=", ".join(device.reasons),
            )
        return PrivilegedResult(
            ok=True,
            message=f"Interfaz {device.iface.name} detectada.",
            technical=f"{device.iface.name} · {device.iface.phy}",
        )

    def _scan(self) -> PrivilegedResult:
        device_id = getattr(self, "_plan_device_id", "")
        device = self._device(device_id)
        if device is None or device.iface is None:
            return PrivilegedResult(
                ok=False, code="no_interface", message="No hay interfaz para escanear."
            )
        ok, networks, technical = self.detector.network.scan(device.iface.name)
        if not ok:
            return PrivilegedResult(
                ok=False, code="scan_failed", message="El escaneo no funcionó.", technical=technical
            )
        if not networks:
            return PrivilegedResult(
                ok=True,
                message="El escaneo funciona, pero no hay redes visibles.",
                technical=technical,
            )
        return PrivilegedResult(
            ok=True,
            message=f"{len(networks)} redes detectadas.",
            technical=technical,
        )

    def _verify_ready(self) -> PrivilegedResult:
        device_id = getattr(self, "_plan_device_id", "")
        device = self._device(device_id)
        if device is None:
            return PrivilegedResult(
                ok=False, code="device_missing", message="El adaptador ya no está conectado."
            )
        if device.status is not DeviceStatus.READY:
            return PrivilegedResult(
                ok=False,
                code="not_ready",
                message="El adaptador todavía no está listo.",
                technical=", ".join(device.reasons),
            )
        return PrivilegedResult(
            ok=True,
            message="Adaptador listo y verificado.",
            technical=f"{device.iface.name if device.iface else ''} · {device.driver.module}",
        )

    # ------------------------------------------------------------------
    def execute_with_plan_device(self, plan: Plan, cancel: Event | None = None) -> PlanResult:
        """Alias explícito para llamadas externas que ya fijan el dispositivo."""
        return self.execute(plan, cancel)
