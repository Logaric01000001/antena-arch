"""Ejecutor: cancelación, desconexión y verificaciones reales simuladas."""

from __future__ import annotations


from antena.core.detect import DetectionResult, Detector
from antena.core.executor import PlanExecutor
from antena.core.models import Plan, PlanStage, StageEvent
from antena.core.planner import build_check_plan
from antena.core.privileged import PrivilegedResult


class FakeClient:
    available = True

    def __init__(self, result: PrivilegedResult | None = None) -> None:
        self.result = result or PrivilegedResult(ok=True, message="ok")
        self.calls: list[tuple[str, dict]] = []

    def call(self, operation, payload, on_progress=None, cancel=None):
        self.calls.append((operation, payload))
        return self.result


class StubDetector:
    def __init__(self, results: list[DetectionResult]) -> None:
        self.results = results
        self.index = 0

    def detect(self) -> DetectionResult:
        current = self.results[min(self.index, len(self.results) - 1)]
        self.index += 1
        return current

    def environment(self):
        return self.results[0].environment


def _usb(result: DetectionResult):
    return next(item for item in result.devices if item.kind == "usb")


def test_cancel_authorization_does_not_report_success(env):
    env.add_aic(storage=True)
    result = Detector(paths=env.paths, runner=env.runner).detect()
    device = _usb(result)
    client = FakeClient(PrivilegedResult(ok=False, code="cancelled", cancelled=True))
    events: list[StageEvent] = []
    plan = Plan(
        recipe_id="aic8800d80",
        device_id=device.id,
        kind="setup",
        stages=[
            PlanStage(
                key="stage.modeswitch",
                op="priv:switch_mode",
                payload={"recipe_id": "aic8800d80", "usb_path": "1-1"},
            )
        ],
    )
    outcome = PlanExecutor(StubDetector([result]), client, events.append).execute(plan)
    assert outcome.cancelled is True
    assert outcome.ok is False
    assert events[-1].state == "cancelled"
    assert client.calls


def test_disconnect_during_install_fails_verification(env):
    env.add_aic(storage=True)
    result = Detector(paths=env.paths, runner=env.runner).detect()
    device = _usb(result)
    empty = DetectionResult(devices=[], environment=result.environment)
    client = FakeClient(PrivilegedResult(ok=True, message="instalado"))
    events: list[StageEvent] = []
    plan = Plan(
        recipe_id="aic8800d80",
        device_id=device.id,
        kind="setup",
        stages=[
            PlanStage(
                key="stage.driver",
                op="priv:install_driver",
                payload={"recipe_id": "aic8800d80", "usb_path": "1-1"},
            ),
            PlanStage(key="stage.interface", op="local:verify_interface", payload={"timeout": 0}),
        ],
    )
    outcome = PlanExecutor(StubDetector([result, empty]), client, events.append).execute(plan)
    assert outcome.ok is False
    assert outcome.failed_stage == "stage.interface"
    assert any(event.state == "failed" for event in events)


def test_existing_driver_stage_is_skipped(env):
    env.add_aic()
    result = Detector(paths=env.paths, runner=env.runner).detect()
    device = _usb(result)
    client = FakeClient()
    events: list[StageEvent] = []
    plan = Plan(
        recipe_id="aic8800d80",
        device_id=device.id,
        kind="setup",
        stages=[
            PlanStage(
                key="stage.driver",
                op="priv:install_driver",
                payload={"recipe_id": "aic8800d80", "usb_path": "1-1"},
            )
        ],
    )
    outcome = PlanExecutor(StubDetector([result]), client, events.append).execute(plan)
    assert outcome.ok is True
    assert client.calls == []
    assert events[-1].state == "skipped"


def test_real_scan_plan_uses_only_the_selected_interface(env):
    env.add_internal()
    env.add_aic()
    detector = Detector(paths=env.paths, runner=env.runner)
    result = detector.detect()
    device = _usb(result)
    plan = build_check_plan(device)
    events: list[StageEvent] = []
    outcome = PlanExecutor(detector, FakeClient(), events.append).execute(plan)
    assert outcome.ok is True
    assert any(event.state == "ok" and "redes" in event.message for event in events)
    scan_calls = [call for call in env.runner.calls if "wifi" in call]
    assert scan_calls
    assert all("wlan0" not in " ".join(call) for call in scan_calls)
