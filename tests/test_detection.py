"""Detección de hardware: 20 escenarios, sin tocar el sistema real."""

from __future__ import annotations


from antena.core.detect import Detector
from antena.core.models import Confidence, DeviceStatus, UsbStage


def detect(env):
    return Detector(paths=env.paths, runner=env.runner).detect()


def usb(env, device_id="usb:1-1"):
    return detect(env).by_id(device_id)


def test_01_no_adapters(env):
    result = detect(env)
    assert result.devices == []
    assert result.errors == []


def test_02_one_functional_adapter(env):
    env.add_aic()
    device = usb(env)
    assert device is not None
    assert device.status is DeviceStatus.READY
    assert device.recipe_id == "aic8800d80"
    assert device.iface is not None and device.iface.name == "wlan1"
    assert device.driver.module == "aic8800_fdrv"
    assert device.driver.loaded is True
    assert "reason.ready" in device.reasons


def test_03_two_adapters(env):
    env.add_aic()
    env.add_kernel_usb(
        path="1-2",
        vid="0e8d",
        pid="7601",
        driver="mt7601u",
        product="MT7601U",
        interface="wlan2",
        phy="phy2",
    )
    result = detect(env)
    usb_devices = [item for item in result.devices if item.kind == "usb"]
    assert len(usb_devices) == 2
    names = {item.name for item in usb_devices}
    assert "AIC8800D80" in names
    assert "MediaTek MT7601U" in names


def test_04_aic_in_storage_mode(env):
    env.add_aic(storage=True)
    device = usb(env)
    assert device is not None
    assert device.usb_stage is UsbStage.STORAGE
    assert device.status is DeviceStatus.NEEDS_SETUP
    assert device.confidence is Confidence.CONFIRMED
    assert "reason.storage_mode" in device.reasons
    assert device.iface is None


def test_04b_storage_id_alone_is_not_enough(env):
    env.add_usb(
        path="1-3",
        vid="1111",
        pid="1111",
        product="USB Flash Drive",
        manufacturer="Generic",
        device_class=8,
        interface_class=8,
        interface_name=None,
        driver="",
        phy="",
    )
    assert detect(env).devices == []


def test_05_transitional_usb_stage(env):
    env.add_aic(pid="8d80", interface=None)
    device = usb(env)
    assert device is not None
    assert device.usb_stage is UsbStage.TRANSITIONAL
    assert device.status is DeviceStatus.NEEDS_ATTENTION
    assert "reason.reconnecting" in device.reasons


def test_06_operational_stage_with_interface(env):
    env.add_aic(pid="8d83")
    device = usb(env)
    assert device is not None
    assert device.usb_stage is UsbStage.OPERATIONAL
    assert device.status is DeviceStatus.READY


def test_12_unknown_chipset_is_reported_not_guessed(env):
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
    device = usb(env, "usb:1-4")
    assert device is not None
    assert device.status is DeviceStatus.UNSUPPORTED
    assert device.recipe_id is None
    assert "reason.unknown_chipset" in device.reasons


def test_15_networkmanager_unmanaged(env):
    env.add_aic(nm_state="unmanaged")
    device = usb(env)
    assert device is not None
    assert device.status is DeviceStatus.NEEDS_ATTENTION
    assert "reason.nm_unmanaged" in device.reasons


def test_16_driver_conflict_is_visible(env):
    env.add_aic()
    env.set_package("aic8800d80-dkms", "1.0.0-6")
    device = usb(env)
    assert device is not None
    assert device.driver.conflicts
    assert any("aic8800d80-dkms" in item for item in device.driver.conflicts)
    assert "reason.driver_conflict" in device.reasons


def test_17_internal_wifi_is_untouched(env):
    env.add_internal()
    env.add_aic()
    result = detect(env)
    internal = next(item for item in result.devices if item.kind == "pci")
    external = next(item for item in result.devices if item.kind == "usb")
    assert internal.iface.name == "wlan0"
    assert external.iface.name == "wlan1"
    assert internal.status is DeviceStatus.READY
    assert internal.recipe_id is None
    # Cada dispositivo conserva su propia interfaz.
    assert internal.iface.name != external.iface.name


def test_18_capabilities_verified_vs_advertised(env):
    env.add_aic()
    device = usb(env)
    assert device is not None
    assert "monitor_mode" in device.capabilities_verified
    assert "packet_injection" not in device.capabilities_verified
    assert "monitor" in device.capabilities_advertised
    recipe = next(
        item for item in Detector(paths=env.paths, runner=env.runner).recipes if item.id == "aic8800d80"
    )
    assert "packet_injection" in recipe.unverified_capabilities


def test_usb_driver_is_read_from_interface_not_netdev(env):
    env.add_aic()
    device = usb(env)
    assert device is not None
    assert device.driver.module == "aic8800_fdrv"
    assert device.iface is not None
    # El driver del netdev USB es "usb"; el módulo real está en la interfaz USB.
    assert device.driver.module != "usb"


def test_firmware_missing_is_detected(env):
    env.add_aic(firmware=False)
    device = usb(env)
    assert device is not None
    assert device.status is DeviceStatus.NEEDS_ATTENTION
    assert "reason.firmware_missing" in device.reasons


def test_untested_kernel_is_a_warning_not_a_false_success(env, monkeypatch):
    env.add_aic()
    monkeypatch.setattr(
        "antena.core.detect.Detector.environment",
        lambda self: __import__("antena.core.models", fromlist=["Environment"]).Environment(
            kernel="9.9.9-arch1-1",
            distro="Arch Linux",
            dkms_available=True,
            usb_modeswitch_available=True,
            nm_available=True,
            iw_available=True,
            tcpdump_available=True,
            headers_ok=True,
            headers_package="linux-headers",
            pacman_available=True,
        ),
    )
    device = usb(env)
    assert device is not None
    assert device.status is DeviceStatus.READY
    assert "reason.kernel_untested" in device.reasons


def test_rfkill_soft_block(env):
    env.add_aic()
    for entry in (env.sys / "class" / "rfkill").glob("rfkill*"):
        (entry / "soft").write_text("1\n")
    device = usb(env)
    assert device is not None
    assert device.status is DeviceStatus.NEEDS_ATTENTION
    assert "reason.rfkill_blocked" in device.reasons


def test_19_reconnect_after_modeswitch_is_redetected(env):
    import shutil

    env.add_aic(storage=True)
    assert usb(env).usb_stage is UsbStage.STORAGE
    # El dispositivo se reenumera tras el cambio de modo: desaparece la
    # entrada de almacenamiento y aparece la operativa con interfaz.
    shutil.rmtree(env.sys / "bus" / "usb" / "devices" / "1-1")
    env.add_aic(pid="8d83")
    device = usb(env)
    assert device is not None
    assert device.usb_stage is UsbStage.OPERATIONAL
    assert device.status is DeviceStatus.READY
    assert device.iface is not None and device.iface.name == "wlan1"


def test_18b_monitor_is_advertised_but_not_verified_for_kernel_driver(env):
    env.add_kernel_usb(
        path="1-2",
        vid="0e8d",
        pid="7601",
        driver="mt7601u",
        product="MT7601U",
        interface="wlan2",
        phy="phy2",
    )
    device = usb(env, "usb:1-2")
    assert device is not None
    assert "monitor" in device.capabilities_advertised
    assert device.capabilities_verified == ()
