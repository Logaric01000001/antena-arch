"""Planes: idempotencia, aislamiento y orden de operaciones."""

from __future__ import annotations


import antena.core.planner as planner
from antena.core.detect import Detector
from antena.core.diagnose import Diagnostics
from antena.core.planner import (
    build_check_plan,
    build_repair_plan,
    build_setup_plan,
    plan_needs_helper,
    persistence_installed,
)


def detect(env):
    return Detector(paths=env.paths, runner=env.runner).detect()


def test_repeat_install_is_idempotent(env, monkeypatch, tmp_path):
    env.add_aic()
    result = detect(env)
    device = next(item for item in result.devices if item.kind == "usb")
    persistence = tmp_path / "99-antena.rules"
    persistence.write_text("# Managed by Antena\n")
    monkeypatch.setattr(planner, "load_state", lambda: {"version": 1, "files": {}, "driver": None})
    monkeypatch.setattr(
        planner,
        "files_for",
        lambda state, owner: [str(persistence)] if owner == "persistence:aic8800d80" else [],
    )
    assert persistence_installed("aic8800d80")
    plan = build_setup_plan(device, result.environment, Detector(paths=env.paths, runner=env.runner).recipes)
    ops = [stage.op for stage in plan.stages]
    assert "priv:install_driver" not in ops
    assert "priv:switch_mode" not in ops
    assert "priv:load_modules" not in ops
    assert "priv:install_persistence" not in ops
    assert "local:scan" in ops
    assert "local:verify_ready" in ops


def test_setup_plan_isolated_to_selected_adapter(env, monkeypatch):
    monkeypatch.setattr(planner, "load_state", lambda: {"version": 1, "files": {}, "driver": None})
    monkeypatch.setattr(planner, "files_for", lambda state, owner: [])
    env.add_internal()
    env.add_aic(storage=True)
    result = detect(env)
    device = next(item for item in result.devices if item.kind == "usb")
    plan = build_setup_plan(device, result.environment, Detector(paths=env.paths, runner=env.runner).recipes)
    payload_text = repr([stage.payload for stage in plan.stages])
    assert "wlan0" not in payload_text
    assert "wlan1" in payload_text or "1-1" in payload_text
    assert any(stage.op == "priv:switch_mode" for stage in plan.stages)
    assert not any("wlan0" in str(value) for stage in plan.stages for value in stage.payload.values())
    # La persistencia se planifica desde el modo almacenamiento, pero se
    # ejecuta después del cambio de modo y de verificar la interfaz.
    ops = [stage.op for stage in plan.stages]
    assert "priv:install_persistence" in ops
    assert ops.index("priv:switch_mode") < ops.index("priv:install_persistence")
    assert ops.index("local:verify_interface") < ops.index("priv:install_persistence")
    assert ops[-1] == "local:verify_ready"


def test_ready_device_check_plan_is_read_only(env):
    env.add_aic()
    result = detect(env)
    device = next(item for item in result.devices if item.kind == "usb")
    plan = build_check_plan(device)
    assert [stage.op for stage in plan.stages] == ["local:scan", "local:verify_ready"]
    assert not plan_needs_helper(plan)


def test_repair_plan_deduplicates_checks(env):
    env.add_aic(nm_state="unmanaged")
    result = detect(env)
    device = next(item for item in result.devices if item.kind == "usb")
    checks, _ = Diagnostics(Detector(paths=env.paths, runner=env.runner), helper_available=True).run(device.id)
    plan = build_repair_plan(device, checks, Detector(paths=env.paths, runner=env.runner).recipes)
    ops = [stage.op for stage in plan.stages]
    assert ops.count("priv:nm_manage") == 1
    assert ops[-1] == "local:verify_ready"


def test_persistence_installed_requires_files_to_exist(monkeypatch, tmp_path):
    missing = tmp_path / "gone.rules"
    monkeypatch.setattr(planner, "load_state", lambda: {"version": 1, "files": {}, "driver": None})
    monkeypatch.setattr(
        planner,
        "files_for",
        lambda state, owner: [str(missing)] if owner == "persistence:aic8800d80" else [],
    )
    assert persistence_installed("aic8800d80") is False
    missing.write_text("# Managed by Antena\n")
    assert persistence_installed("aic8800d80") is True
