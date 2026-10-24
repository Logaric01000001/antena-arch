"""Diagnóstico y reparación sobre dispositivos simulados."""

from __future__ import annotations

from antena.core.detect import Detector
from antena.core.diagnose import Diagnostics
from antena.core.models import DeviceStatus
from antena.core.planner import build_repair_plan, plan_needs_helper


def detect(env):
    return Detector(paths=env.paths, runner=env.runner).detect()


def test_ready_device_has_no_problems(env):
    env.add_aic()
    checks, _ = Diagnostics(Detector(paths=env.paths, runner=env.runner), helper_available=True).run()
    assert [item for item in checks if item.status in {"error", "warning"}] == []


def test_storage_mode_plan_installs_then_switches(env):
    env.add_aic(storage=True)
    result = detect(env)
    device = next(item for item in result.devices if item.kind == "usb")
    assert device.status is DeviceStatus.NEEDS_SETUP
    checks, _ = Diagnostics(Detector(paths=env.paths, runner=env.runner), helper_available=True).run(device.id)
    plan = build_repair_plan(device, checks, Detector(paths=env.paths, runner=env.runner).recipes)
    ops = [stage.op for stage in plan.stages]
    assert "priv:install_driver" in ops
    assert "priv:switch_mode" in ops
    assert ops[-1] == "local:verify_ready"
    assert plan_needs_helper(plan)
    # El orden nunca activa el módulo antes de instalar y cambiar de modo.
    assert ops.index("priv:install_driver") < ops.index("priv:switch_mode")
    assert ops.index("priv:switch_mode") < ops.index("priv:load_modules")


def test_dkms_failure_and_headers_are_actionable(env):
    env.add_aic(dkms_state="build (bad return status)")
    env.add_module("aic8800_fdrv", installed=False, loaded=False)
    env.set_headers(False)
    result = detect(env)
    device = next(item for item in result.devices if item.kind == "usb")
    checks, _ = Diagnostics(Detector(paths=env.paths, runner=env.runner), helper_available=True).run(device.id)
    by_id = {item.id: item for item in checks}
    assert by_id["headers"].status == "warning"
    assert by_id["headers"].action is not None
    assert by_id["dkms"].status == "error"
    assert by_id["dkms"].action is not None
    assert by_id["dkms"].action.op == "dkms_rebuild"
    assert by_id["driver_installed"].status == "error"
    plan = build_repair_plan(device, checks, Detector(paths=env.paths, runner=env.runner).recipes)
    assert plan.stages[0].op == "priv:install_packages"
    assert "linux-headers" in plan.stages[0].payload["packages"]


def test_kernel_incompatible_is_not_reported_as_ready(env):
    env.add_aic(dkms_kernel="6.12.1-arch1-1")
    env.add_module("aic8800_fdrv", installed=False, loaded=False, aliases=[])
    result = detect(env)
    device = next(item for item in result.devices if item.kind == "usb")
    assert device.status is DeviceStatus.NEEDS_SETUP
    checks, _ = Diagnostics(Detector(paths=env.paths, runner=env.runner), helper_available=True).run(device.id)
    by_id = {item.id: item for item in checks}
    assert by_id["driver_installed"].status == "error"
    assert "6.12.1" in by_id["dkms"].detail
    assert by_id["dkms"].action is not None


def test_nm_unmanaged_has_specific_action(env):
    env.add_aic(nm_state="unmanaged")
    result = detect(env)
    device = next(item for item in result.devices if item.kind == "usb")
    checks, _ = Diagnostics(Detector(paths=env.paths, runner=env.runner), helper_available=True).run(device.id)
    by_id = {item.id: item for item in checks}
    assert by_id["nm_managed"].status == "warning"
    assert by_id["nm_managed"].action.op == "nm_manage"
    assert by_id["nm_managed"].action.payload["iface"] == "wlan1"


def test_default_diagnostic_target_is_external(env):
    env.add_internal()
    env.add_aic()
    checks, detection = Diagnostics(Detector(paths=env.paths, runner=env.runner), helper_available=True).run()
    identity = next(item for item in checks if item.id == "identity")
    assert "AIC8800D80" in identity.detail
    assert detection.devices[0].kind == "pci"


def test_unknown_device_has_no_invented_fix(env):
    env.add_usb(
        path="1-4",
        vid="0bda",
        pid="8812",
        product="RTL8812AU",
        manufacturer="Realtek",
        device_class=0,
        interface_class=255,
        interface_name=None,
        driver="",
        phy="",
    )
    result = detect(env)
    device = next(item for item in result.devices if item.kind == "usb")
    checks, _ = Diagnostics(Detector(paths=env.paths, runner=env.runner), helper_available=True).run(device.id)
    by_id = {item.id: item for item in checks}
    assert by_id["identity"].status == "warning"
    assert by_id["driver_installed"].status == "unknown"
    assert by_id["interface"].status == "error"


def test_helper_missing_is_a_warning_not_a_failure(env):
    env.add_aic()
    checks, _ = Diagnostics(Detector(paths=env.paths, runner=env.runner), helper_available=False).run()
    helper = next(item for item in checks if item.id == "helper")
    assert helper.status == "warning"
