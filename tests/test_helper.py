"""Seguridad del helper, integridad, pcap y limpieza sin daños colaterales."""

from __future__ import annotations

import json
import tarfile
import urllib.error
from pathlib import Path

import pytest

import antena.priv.helper as helper
import antena.priv.state as state_store
from antena.core.catalog import CatalogError, load_recipes
from antena.core.models import UsbRecord
from antena.core.runner import CommandRunner
from antena.core.sysfs import Sysfs
from antena.priv.pcap import count_beacons
from fakeenv import CATALOG, FakeRunner


def aic_recipe():
    return next(item for item in load_recipes(CATALOG) if item.id == "aic8800d80")


def test_modeswitch_arguments_are_fixed_and_hex():
    recipe = aic_recipe()
    args = helper.build_modeswitch_args(recipe)
    assert args[0] == "usb_modeswitch"
    assert args[1:5] == ["-v", "1111", "-p", "1111"]
    assert args[5] == "-M"
    assert args[6] == recipe.modeswitch["message"]
    assert args[7] == "-2"
    assert args[8] == recipe.modeswitch["message2"]
    with pytest.raises(helper.HelperError):
        helper.require_usb_path({"usb_path": "../../etc/passwd"})
    with pytest.raises(helper.HelperError):
        helper.require_usb_path({"usb_path": "1-1;reboot"})


def test_storage_identity_requires_more_than_usb_id(env):
    recipe = aic_recipe()
    env.add_aic(storage=True, product="88M80", manufacturer="AIC")
    device = helper.verify_modeswitch_target(recipe, "1-1", sysfs=Sysfs(env.paths))
    assert device.usb_id == "1111:1111"

    env2 = type(env)(env.root / "other")
    env2.add_aic(storage=True, vid="1111", pid="1111", product="USB Flash", manufacturer="AIC")
    with pytest.raises(helper.HelperError) as exc:
        helper.verify_modeswitch_target(recipe, "1-1", sysfs=Sysfs(env2.paths))
    assert exc.value.code == "identity_mismatch"


def test_verify_usb_identity_rejects_changed_vid(env):
    env.add_aic(storage=True, vid="2222", pid="1111", product="88M80", manufacturer="AIC")
    with pytest.raises(helper.HelperError) as exc:
        helper.verify_usb_identity("1-1", "1111:1111", sysfs=Sysfs(env.paths))
    assert exc.value.code == "identity_mismatch"


def _storage_record() -> UsbRecord:
    return UsbRecord(
        path_name="1-1",
        vid="1111",
        pid="1111",
        product="88M80",
        manufacturer="AIC",
        device_class=8,
        interface_classes=((8, 6, 80),),
    )


def _operational_record() -> UsbRecord:
    return UsbRecord(
        path_name="1-1",
        vid="a69c",
        pid="8d83",
        product="AIC 8800D80",
        manufacturer="AICSemi",
        device_class=0,
        interface_classes=((255, 255, 255),),
        net_names=("wlan1",),
    )


class SwitchingSysfs:
    records = [_storage_record()]

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def usb_devices(self):
        return list(type(self).records)


class SwitchingRunner(FakeRunner):
    def run(self, args, timeout=15.0, env=None):
        outcome = super().run(args, timeout, env)
        if args and "usb_modeswitch" in str(args[0]):
            SwitchingSysfs.records = [_operational_record()]
        return outcome


def test_switch_mode_simulated_with_reenumeration(monkeypatch):
    SwitchingSysfs.records = [_storage_record()]
    runner = SwitchingRunner()
    monkeypatch.setattr(helper, "Sysfs", SwitchingSysfs)
    monkeypatch.setattr(helper, "RUNNER", runner)
    outcome = helper.op_switch_mode(
        {"recipe_id": "aic8800d80", "usb_path": "1-1"}
    )
    assert outcome["ok"] is True
    assert outcome["usb_id"] == "a69c:8d83"
    called = [" ".join(call) for call in runner.calls]
    assert any("usb_modeswitch -v 1111 -p 1111 -M" in item for item in called)


def test_switch_mode_is_idempotent_when_already_operational(monkeypatch):
    SwitchingSysfs.records = [_operational_record()]
    runner = SwitchingRunner()
    monkeypatch.setattr(helper, "Sysfs", SwitchingSysfs)
    monkeypatch.setattr(helper, "RUNNER", runner)
    outcome = helper.op_switch_mode(
        {"recipe_id": "aic8800d80", "usb_path": "1-1"}
    )
    assert outcome["ok"] is True
    assert outcome.get("already_switched") is True
    assert not any("usb_modeswitch" in str(call[0]) for call in runner.calls)


def test_package_allowlist_rejects_arbitrary_packages(monkeypatch):
    calls: list[list[str]] = []

    class NoRun:
        def run(self, args, timeout=15.0, env=None):
            calls.append(list(args))
            return CommandRunner().run(["true"])

    monkeypatch.setattr(helper, "RUNNER", NoRun())
    with pytest.raises(helper.HelperError) as exc:
        helper.op_install_packages({"packages": ["bash"]})
    assert exc.value.code == "package_not_allowed"
    assert calls == []


def test_unknown_recipe_is_rejected():
    with pytest.raises(helper.HelperError) as exc:
        helper.require_recipe({"recipe_id": "does-not-exist"})
    assert exc.value.code == "unknown_recipe"


def test_safe_extract_rejects_traversal(tmp_path):
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("../escape.txt")
        payload = b"nope"
        info.size = len(payload)
        import io

        tar.addfile(info, io.BytesIO(payload))
    with pytest.raises(helper.HelperError) as exc:
        helper.safe_extract(archive, tmp_path / "dest")
    assert exc.value.code == "unsafe_archive"
    assert not (tmp_path / "escape.txt").exists()


def test_no_internet_is_classified(monkeypatch, tmp_path):
    def offline(*_args, **_kwargs):
        raise urllib.error.URLError("network is unreachable")

    monkeypatch.setattr(helper.urllib.request, "urlopen", offline)
    with pytest.raises(helper.HelperError) as exc:
        helper.download_verified("https://example.invalid/driver.tar.gz", "a" * 64, 10, tmp_path / "x")
    assert exc.value.code == "download_failed"


def test_pcap_counts_beacons(env, tmp_path):
    capture = tmp_path / "beacons.pcap"
    env.write_pcap(capture, beacons=3, others=2)
    counts = count_beacons(capture)
    assert counts == {"packets": 5, "beacons": 3}


def test_catalog_rejects_bad_hash(tmp_path):
    source = CATALOG / "aic8800d80.json"
    data = json.loads(source.read_text())
    data["driver"]["source_sha256"] = "not-a-hash"
    target = tmp_path / "bad.json"
    target.write_text(json.dumps(data))
    with pytest.raises(CatalogError):
        load_recipes(tmp_path)


def _managed_state(tmp_path: Path) -> dict:
    return {
        "version": 1,
        "files": {},
        "driver": None,
    }


def test_uninstall_keeps_third_party_and_only_removes_owned_files(env, monkeypatch, tmp_path):
    state_file = tmp_path / "var" / "state.json"
    monkeypatch.setattr(state_store, "SYSTEM_STATE_FILE", state_file)
    rule = tmp_path / "etc" / "udev" / "99-antena.rules"
    modules = tmp_path / "etc" / "modules-load" / "antena-aic8800d80.conf"
    driver_dir = tmp_path / "opt" / "driver-src"
    firmware = tmp_path / "opt" / "firmware.bin"
    foreign = tmp_path / "opt" / "third-party.ko"
    for path in (rule, modules, firmware, foreign):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Managed by Antena\n" if path in (rule, modules) else "binary\n")
    driver_dir.mkdir(parents=True, exist_ok=True)
    (driver_dir / "module.c").write_text("// driver\n")

    state = _managed_state(tmp_path)
    state["files"] = {
        str(rule): "persistence:aic8800d80",
        str(modules): "persistence:aic8800d80",
        str(driver_dir): "driver:aic8800d80",
        str(firmware): "driver:aic8800d80",
        str(foreign): "thirdparty:vendor",
    }
    state["driver"] = {
        "recipe_id": "aic8800d80",
        "package": "aic8800-fdrv-dkms",
        "version": "6.4.3.0",
        "managed_by_antena": True,
    }
    state_store.save_state(state, state_file)

    from fakeenv import FakeRunner

    runner = FakeRunner()
    runner.set("udevadm control --reload-rules", "")
    runner.set("dkms remove", "")
    monkeypatch.setattr(helper, "RUNNER", runner)

    outcome = helper.op_cleanup({})
    assert outcome["ok"] is True
    assert not rule.exists() and not modules.exists()
    assert driver_dir.exists() and firmware.exists()
    assert foreign.exists()
    assert outcome["driver_removed"] is False

    # Con consentimiento explícito, Antena retira su propio controlador,
    # pero nunca archivos ajenos.
    rule.write_text("# Managed by Antena\n")
    modules.write_text("# Managed by Antena\n")
    state = state_store.load_state()
    state["files"].update({str(rule): "persistence:aic8800d80", str(modules): "persistence:aic8800d80"})
    state_store.save_state(state, state_file)
    outcome = helper.op_cleanup({"remove_driver": True})
    assert outcome["driver_removed"] is True
    assert not driver_dir.exists()
    assert not firmware.exists()
    assert foreign.exists()
    assert any("dkms" in " ".join(call) for call in runner.calls)


def test_uninstall_never_removes_unmanaged_driver(env, monkeypatch, tmp_path):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(state_store, "SYSTEM_STATE_FILE", state_file)
    driver_dir = tmp_path / "vendor-driver"
    driver_dir.mkdir()
    (driver_dir / "module.c").write_text("// third party\n")
    state = _managed_state(tmp_path)
    state["files"] = {str(driver_dir): "driver:vendor"}
    state["driver"] = {
        "recipe_id": "aic8800d80",
        "package": "aic8800-fdrv-dkms",
        "version": "6.4.3.0",
        "managed_by_antena": False,
    }
    state_store.save_state(state, state_file)
    from fakeenv import FakeRunner

    runner = FakeRunner()
    runner.set("udevadm control --reload-rules", "")
    monkeypatch.setattr(helper, "RUNNER", runner)
    outcome = helper.op_cleanup({"remove_driver": True})
    assert outcome["driver_removed"] is False
    assert driver_dir.exists()
    assert not any("dkms remove" in " ".join(call) for call in runner.calls)
