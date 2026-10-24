"""Construcción de planes: qué se hará, en qué orden y por qué."""

from __future__ import annotations

from pathlib import Path

from antena.constants import ALLOWED_PACMAN_PACKAGES
from antena.core.catalog import Recipe, find_recipe
from antena.core.models import (
    CheckResult,
    DeviceInfo,
    DeviceStatus,
    Environment,
    Plan,
    PlanStage,
    UsbStage,
)
from antena.priv.state import files_for, load_state

STAGE_KEYS = {
    "install_packages": "stage.packages",
    "install_driver": "stage.driver",
    "switch_mode": "stage.modeswitch",
    "load_modules": "stage.modules",
    "install_persistence": "stage.persistence",
    "rfkill_unblock": "stage.rfkill",
    "nm_manage": "stage.nm",
    "dkms_rebuild": "stage.dkms",
    "scan": "stage.scan",
}

OP_ORDER = {
    "install_packages": 10,
    "install_driver": 20,
    "switch_mode": 30,
    "load_modules": 40,
    "rfkill_unblock": 50,
    "nm_manage": 60,
    "dkms_rebuild": 70,
    "install_persistence": 80,
}


def _recipe_for(device: DeviceInfo, recipes: tuple[Recipe, ...]) -> Recipe | None:
    return find_recipe(recipes, device.recipe_id) if device.recipe_id else None


def persistence_installed(recipe_id: str) -> bool:
    """Solo cuenta como instalada si los archivos registrados siguen ahí."""
    paths = files_for(load_state(), f"persistence:{recipe_id}")
    return bool(paths) and all(Path(path).exists() for path in paths)


def missing_dependencies(recipe: Recipe | None, environment: Environment) -> list[str]:
    missing: list[str] = []
    if recipe is None:
        return missing
    if recipe.is_kernel_native:
        return missing
    if not environment.dkms_available:
        missing.append("dkms")
    if recipe.modeswitch and not environment.usb_modeswitch_available:
        missing.append("usb_modeswitch")
    if (
        not environment.headers_ok
        and environment.headers_package
        and environment.headers_package in ALLOWED_PACMAN_PACKAGES
    ):
        missing.append(environment.headers_package)
    return missing


def build_setup_plan(
    device: DeviceInfo, environment: Environment, recipes: tuple[Recipe, ...]
) -> Plan:
    recipe = _recipe_for(device, recipes)
    plan = Plan(recipe_id=recipe.id if recipe else "", device_id=device.id, kind="setup")
    if recipe is None or device.status is DeviceStatus.UNSUPPORTED:
        return plan
    plan.stages.append(
        PlanStage(key="stage.environment", op="local:verify_environment", payload={})
    )
    dependencies = missing_dependencies(recipe, environment)
    if dependencies:
        plan.stages.append(
            PlanStage(
                key="stage.packages",
                op="priv:install_packages",
                payload={"packages": dependencies},
            )
        )
    if not recipe.is_kernel_native and not device.driver.installed_for_running_kernel:
        plan.stages.append(
            PlanStage(
                key="stage.driver",
                op="priv:install_driver",
                payload={"recipe_id": recipe.id, "usb_path": device.usb.path_name},
            )
        )
    if device.usb_stage is UsbStage.STORAGE:
        plan.stages.append(
            PlanStage(
                key="stage.modeswitch",
                op="priv:switch_mode",
                payload={"recipe_id": recipe.id, "usb_path": device.usb.path_name},
            )
        )
    if not device.driver.loaded:
        plan.stages.append(
            PlanStage(
                key="stage.modules",
                op="priv:load_modules",
                payload={"recipe_id": recipe.id, "usb_path": device.usb.path_name},
            )
        )
    plan.stages.append(
        PlanStage(
            key="stage.interface",
            op="local:verify_interface",
            payload={"timeout": 20},
        )
    )
    if recipe.verification.get("scan", False):
        plan.stages.append(PlanStage(key="stage.scan", op="local:scan", payload={}))
    if (
        recipe.persistence
        and device.usb_stage is UsbStage.OPERATIONAL
        and not persistence_installed(recipe.id)
    ):
        plan.stages.append(
            PlanStage(
                key="stage.persistence",
                op="priv:install_persistence",
                payload={"recipe_id": recipe.id, "usb_path": device.usb.path_name},
            )
        )
    plan.stages.append(PlanStage(key="stage.verify", op="local:verify_ready", payload={}))
    return plan


def build_repair_plan(
    device: DeviceInfo, checks: list[CheckResult], recipes: tuple[Recipe, ...]
) -> Plan:
    recipe = _recipe_for(device, recipes)
    plan = Plan(recipe_id=recipe.id if recipe else "", device_id=device.id, kind="repair")
    actions: dict[tuple[str, str], tuple[int, CheckResult]] = {}
    for check in checks:
        action = check.action
        if action is None:
            continue
        key = (action.op, repr(sorted(action.payload.items())))
        priority = OP_ORDER.get(action.op, 100)
        if key not in actions or priority < actions[key][0]:
            actions[key] = (priority, check)
    ordered = sorted(actions.values(), key=lambda item: item[0])
    for _, check in ordered:
        action = check.action
        assert action is not None
        plan.stages.append(
            PlanStage(
                key=STAGE_KEYS.get(action.op, "stage.verify"),
                op=f"priv:{action.op}" if action.privileged else action.op,
                payload=dict(action.payload),
            )
        )
    if not plan.stages:
        return plan
    plan.stages.append(PlanStage(key="stage.verify", op="local:verify_ready", payload={}))
    return plan


def build_check_plan(device: DeviceInfo) -> Plan:
    """Plan de solo lectura para un adaptador que ya funciona."""
    return Plan(
        recipe_id=device.recipe_id or "",
        device_id=device.id,
        kind="check",
        stages=[
            PlanStage(key="stage.scan", op="local:scan", payload={}),
            PlanStage(key="stage.verify", op="local:verify_ready", payload={}),
        ],
    )


def plan_needs_helper(plan: Plan) -> bool:
    return any(stage.op.startswith("priv:") for stage in plan.stages)
