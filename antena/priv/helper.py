"""Componente privilegiado de Antena.

Se ejecuta únicamente a través de pkexec. No acepta comandos: solo un nombre
de operación cerrado y un JSON validado. Cada operación vuelve a comprobar el
dispositivo real antes de tocar nada.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from antena.constants import (
    ALLOWED_MODULES,
    ALLOWED_PACMAN_PACKAGES,
    MANAGED_MODULES_LOAD_DIR,
    MANAGED_UDEV_DIR,
    VERSION,
)
from antena.core.catalog import Recipe, load_recipes
from antena.core.network import split_nmcli
from antena.core.runner import CommandRunner
from antena.core.sysfs import Sysfs, read_text
from antena.priv import state as state_store
from antena.priv.pcap import count_beacons

USB_PATH_RE = re.compile(r"^[0-9]+-[0-9]+(\.[0-9]+)*$")
RECIPE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
IFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
PHY_RE = re.compile(r"^phy[0-9]+$")
MAX_PAYLOAD = 64 * 1024
MAX_DOWNLOAD = 80 * 1024 * 1024
MANAGED_MARKER = "Managed by Antena"
RUNNER = CommandRunner()


class HelperError(RuntimeError):
    def __init__(self, code: str, message: str, technical: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.technical = technical


def emit(event: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def progress(message: str, technical: str = "") -> None:
    emit({"event": "progress", "message": message, "technical": technical})


def result(ok: bool, message: str = "", technical: str = "", **extra: Any) -> dict[str, Any]:
    data = {"event": "result", "ok": ok, "message": message, "technical": technical}
    data.update(extra)
    return data


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------


def validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HelperError("bad_payload", "El payload debe ser un objeto JSON.")
    if len(json.dumps(payload)) > MAX_PAYLOAD:
        raise HelperError("bad_payload", "El payload es demasiado grande.")
    return payload


def require_str(payload: dict[str, Any], key: str, pattern: re.Pattern[str] | None = None) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise HelperError("bad_payload", f"Falta el campo {key}.")
    if pattern is not None and not pattern.match(value):
        raise HelperError("bad_payload", f"El campo {key} no es válido.")
    return value


def require_usb_path(payload: dict[str, Any]) -> str:
    return require_str(payload, "usb_path", USB_PATH_RE)


def require_recipe(payload: dict[str, Any]) -> Recipe:
    recipe_id = require_str(payload, "recipe_id", RECIPE_ID_RE)
    return load_recipe(recipe_id)


def load_recipe(recipe_id: str) -> Recipe:
    for recipe in load_recipes():
        if recipe.id == recipe_id:
            return recipe
    raise HelperError("unknown_recipe", "La receta no existe en el catálogo.")


def verify_usb_identity(
    usb_path: str, usb_id: str, *, require_storage: bool = False, sysfs: Sysfs | None = None
) -> Any:
    helper_sysfs = sysfs or Sysfs()
    device = next((item for item in helper_sysfs.usb_devices() if item.path_name == usb_path), None)
    if device is None:
        raise HelperError("device_missing", "El adaptador ya no está conectado.")
    if device.usb_id != usb_id.lower():
        raise HelperError(
            "identity_mismatch",
            "El dispositivo cambió de identificador; no se actúa sobre él.",
            f"esperado={usb_id} real={device.usb_id}",
        )
    if require_storage and not device.is_storage:
        raise HelperError("not_storage", "El dispositivo ya no está en modo almacenamiento.")
    return device


def verify_modeswitch_target(recipe: Recipe, usb_path: str, sysfs: Sysfs | None = None) -> Any:
    modeswitch = recipe.modeswitch or {}
    device = verify_usb_identity(
        usb_path,
        f"{modeswitch['vid']}:{modeswitch['pid']}",
        require_storage=False,
        sysfs=sysfs,
    )
    requirements = recipe.storage_requirements()
    manufacturer = device.manufacturer.lower()
    product = device.product.lower()
    if requirements["require_storage_class"] and not device.is_storage:
        raise HelperError("not_storage", "El dispositivo no está en modo almacenamiento.")
    if requirements["manufacturers"] and not any(
        item in manufacturer for item in requirements["manufacturers"]
    ):
        raise HelperError("identity_mismatch", "El fabricante USB no coincide con la receta.")
    if requirements["products"] and not any(item in product for item in requirements["products"]):
        raise HelperError(
            "identity_mismatch",
            "El producto USB no coincide con la receta.",
            f"producto={device.product!r}",
        )
    return device


def build_modeswitch_args(recipe: Recipe) -> list[str]:
    modeswitch = recipe.modeswitch
    if not modeswitch:
        raise HelperError("no_modeswitch", "La receta no define cambio de modo USB.")
    message = str(modeswitch["message"])
    message2 = str(modeswitch.get("message2", ""))
    if not re.fullmatch(r"[0-9a-fA-F]+", message) or len(message) % 2:
        raise HelperError("bad_modeswitch", "Mensaje de cambio de modo inválido.")
    args = [
        "usb_modeswitch",
        "-v",
        str(modeswitch["vid"]),
        "-p",
        str(modeswitch["pid"]),
        "-M",
        message,
    ]
    if message2:
        if not re.fullmatch(r"[0-9a-fA-F]+", message2) or len(message2) % 2:
            raise HelperError("bad_modeswitch", "Segundo mensaje inválido.")
        args.extend(["-2", message2])
    return args


def safe_extract(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            name = member.name
            target = (destination / name).resolve()
            if not str(target).startswith(str(destination.resolve()) + os.sep) and target != destination.resolve():
                raise HelperError("unsafe_archive", "El archivo contiene rutas no seguras.")
            if member.islnk() or member.issym() or member.isdev():
                raise HelperError("unsafe_archive", "El archivo contiene enlaces no permitidos.")
            if not (member.isfile() or member.isdir()):
                continue
        try:
            tar.extractall(destination, filter="data")
        except TypeError:  # Python 3.11 sin el parámetro filter
            tar.extractall(destination)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(url: str, expected_sha: str, expected_size: int, destino: Path) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HelperError("bad_source", "La descarga debe usar HTTPS.")
    progress("Descargando el controlador…")
    request = urllib.request.Request(url, headers={"User-Agent": f"Antena/{VERSION}"})
    written = 0
    try:
        with urllib.request.urlopen(request, timeout=45) as response, destino.open("wb") as out:
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_DOWNLOAD:
                raise HelperError("too_large", "La descarga supera el tamaño permitido.")
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_DOWNLOAD:
                    raise HelperError("too_large", "La descarga supera el tamaño permitido.")
                out.write(chunk)
    except urllib.error.URLError as exc:
        raise HelperError("download_failed", "No se pudo descargar el controlador.", str(exc)) from exc
    if expected_size and written != expected_size:
        raise HelperError(
            "size_mismatch",
            "El tamaño del archivo no coincide con el esperado.",
            f"esperado={expected_size} real={written}",
        )
    actual = sha256_file(destino)
    if actual != expected_sha.lower():
        raise HelperError(
            "hash_mismatch",
            "La verificación de integridad falló. No se instaló nada.",
            f"esperado={expected_sha} real={actual}",
        )


def validate_iface(iface: str, *, require_disconnected: bool = False) -> None:
    if not IFACE_RE.match(iface):
        raise HelperError("bad_iface", "Nombre de interfaz inválido.")
    sysfs = Sysfs()
    if iface not in sysfs.net_names():
        raise HelperError("iface_missing", "La interfaz ya no existe.")
    if not sysfs.net_is_wireless(iface):
        raise HelperError("not_wireless", "La interfaz no es inalámbrica.")
    if require_disconnected:
        value = RUNNER.run(["nmcli", "-t", "-f", "GENERAL.STATE", "device", "show", iface], timeout=10)
        state = ""
        for line in value.stdout.splitlines():
            fields = split_nmcli(line)
            if len(fields) >= 2 and fields[0] == "GENERAL.STATE":
                state = fields[1]
        if "connected" in state and "disconnected" not in state:
            raise HelperError(
                "iface_connected",
                "La interfaz tiene una conexión activa; no se tocará.",
                state,
            )


# ---------------------------------------------------------------------------
# Operaciones
# ---------------------------------------------------------------------------


def op_install_packages(payload: dict[str, Any]) -> dict[str, Any]:
    packages = payload.get("packages")
    if not isinstance(packages, list) or not packages:
        raise HelperError("bad_payload", "Falta la lista de paquetes.")
    normalized: list[str] = []
    for item in packages:
        if not isinstance(item, str) or item not in ALLOWED_PACMAN_PACKAGES:
            raise HelperError("package_not_allowed", "Paquete no permitido.")
        if item not in normalized:
            normalized.append(item)
    progress("Instalando componentes del sistema…")
    result_cmd = RUNNER.run(["pacman", "-S", "--needed", "--noconfirm", *normalized], timeout=600)
    if not result_cmd.ok:
        raise HelperError(
            "pacman_failed",
            "No se pudieron instalar los componentes.",
            (result_cmd.stderr or result_cmd.stdout).strip()[-2000:],
        )
    missing = [item for item in normalized if not RUNNER.run(["pacman", "-Q", item], timeout=10).ok]
    if missing:
        raise HelperError("verify_failed", "La instalación no se pudo verificar.", ", ".join(missing))
    return result(True, "Componentes instalados.", packages=", ".join(normalized))


def op_install_driver(payload: dict[str, Any]) -> dict[str, Any]:
    recipe = require_recipe(payload)
    usb_path = require_usb_path(payload)
    if recipe.is_kernel_native:
        raise HelperError("not_supported", "Esta receta no instala controladores.")
    source = recipe.source
    if not source:
        raise HelperError("no_source", "La receta no define una fuente verificable.")
    device = next((item for item in Sysfs().usb_devices() if item.path_name == usb_path), None)
    if device is None:
        raise HelperError("device_missing", "El adaptador ya no está conectado.")
    if device.usb_id not in recipe.usb_ids:
        raise HelperError("identity_mismatch", "El identificador USB no coincide con la receta.")
    if not recipe.tested_kernels:
        raise HelperError("unverified_driver", "La receta no declara kernels probados.")

    running = read_text(Path("/proc/sys/kernel/osrelease")) or os.uname().release
    state = state_store.load_state()
    driver_state = state.get("driver") or {}

    # Idempotencia: si el módulo ya está instalado para este kernel, no se toca.
    existing = RUNNER.run(["modinfo", "-n", recipe.primary_module], timeout=10)
    dkms_existing = RUNNER.run(["dkms", "status", recipe.dkms_package], timeout=20)
    if existing.ok and existing.stdout.strip():
        dkms_ready = any(
            running in line and "installed" in line for line in dkms_existing.stdout.splitlines()
        )
        if dkms_ready:
            return result(True, "El controlador ya está instalado.", already_installed=True)
        if not driver_state.get("managed_by_antena"):
            raise HelperError(
                "driver_conflict",
                "Ya existe un controlador para este chipset instalado por otro medio.",
                existing.stdout.strip(),
            )

    if not RUNNER.which("dkms"):
        raise HelperError("missing_dependency", "DKMS no está instalado.")
    if not (Path("/lib/modules") / running / "build").exists():
        raise HelperError(
            "headers_missing",
            "Faltan los encabezados del kernel en ejecución.",
            running,
        )

    source_dir = Path("/usr/src") / f"antena-{recipe.dkms_package}-{recipe.driver_version}"
    if source_dir.exists() and not driver_state.get("managed_by_antena"):
        raise HelperError("path_conflict", "Ya existe un directorio de código con ese nombre.")

    with tempfile.TemporaryDirectory(prefix="antena-driver-", dir="/var/tmp") as work:
        workdir = Path(work)
        archive = workdir / "driver.tar.gz"
        download_verified(source["url"], source["sha256"], source["size"], archive)
        progress("Verificando y extrayendo el código…")
        extract_dir = workdir / "src"
        extract_dir.mkdir()
        safe_extract(archive, extract_dir)
        root = extract_dir / source["root"]
        if not root.is_dir():
            raise HelperError("bad_archive", "El archivo no contiene el directorio esperado.")
        for relative in source["dkms_files"]:
            if not (root / relative).exists():
                raise HelperError("bad_archive", f"Falta {relative} en el archivo.")

        if source_dir.exists():
            shutil.rmtree(source_dir)
        source_dir.mkdir(parents=True)
        # El catálogo declara qué archivos forman la raíz DKMS. Se copian
        # conservando su nombre: Makefile/Kconfig/dkms.conf y directorios de
        # módulos. Así una receta nueva no requiere cambiar el helper.
        for relative in source["dkms_files"]:
            origin = root / relative
            target = source_dir / origin.name
            if origin.is_dir():
                shutil.copytree(origin, target)
            else:
                shutil.copy2(origin, target)

        dkms_conf = (source_dir / "dkms.conf").read_text(encoding="utf-8", errors="replace")
        if f'PACKAGE_VERSION="{recipe.driver_version}"' not in dkms_conf:
            raise HelperError("bad_archive", "dkms.conf no declara la versión esperada.")

        progress("Compilando el módulo con DKMS…")
        # Solo se retira el registro DKMS si lo creó esta operación. Un
        # registro previo (aunque esté roto) pertenece a otro origen.
        added_here = False
        if not RUNNER.run(
            ["dkms", "status", recipe.dkms_package], timeout=20
        ).stdout.strip():
            added = RUNNER.run(["dkms", "add", str(source_dir)], timeout=120)
            if not added.ok:
                _rollback_driver(source_dir, recipe, [], None, False)
                raise HelperError("dkms_add_failed", "DKMS no pudo registrar el módulo.", added.stderr[-2000:])
            added_here = True
        built = RUNNER.run(
            ["dkms", "build", "-m", recipe.dkms_package, "-v", recipe.driver_version],
            timeout=1800,
        )
        if not built.ok:
            technical = (built.stdout + "\n" + built.stderr).strip()[-4000:]
            _rollback_driver(source_dir, recipe, [], None, added_here)
            raise HelperError("dkms_build_failed", "La compilación del módulo falló.", technical)
        installed = RUNNER.run(
            ["dkms", "install", "-m", recipe.dkms_package, "-v", recipe.driver_version],
            timeout=600,
        )
        if not installed.ok:
            technical = (installed.stdout + "\n" + installed.stderr).strip()[-4000:]
            _rollback_driver(source_dir, recipe, [], None, added_here)
            raise HelperError("dkms_install_failed", "DKMS no pudo instalar el módulo.", technical)

        firmware_files: list[str] = []
        if source.get("firmware_source") and source.get("firmware_dest"):
            origin = root / source["firmware_source"]
            dest = Path(source["firmware_dest"])
            if not origin.is_dir():
                _rollback_driver(source_dir, recipe, [], None, added_here)
                raise HelperError("bad_archive", "Falta el firmware en el archivo.")
            if not _allowed_firmware_dest(dest):
                _rollback_driver(source_dir, recipe, [], None, added_here)
                raise HelperError("unsafe_path", "Destino de firmware no permitido.")
            progress("Instalando firmware…")
            dest.mkdir(parents=True, exist_ok=True)
            for item in sorted(origin.rglob("*")):
                if not item.is_file():
                    continue
                target = dest / item.relative_to(origin)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                os.chmod(target, 0o644)
                firmware_files.append(str(target))

        depmod = RUNNER.run(["depmod", running], timeout=120)
        if not depmod.ok:
            technical = (depmod.stderr or depmod.stdout).strip()
            _rollback_driver(source_dir, recipe, firmware_files, None, added_here)
            raise HelperError("depmod_failed", "No se pudo actualizar el índice de módulos.", technical)

        probe = RUNNER.run(["modinfo", "-n", recipe.primary_module], timeout=10)
        if not probe.ok or not probe.stdout.strip():
            _rollback_driver(source_dir, recipe, firmware_files, None, added_here)
            raise HelperError("verify_failed", "El módulo no aparece tras la instalación.")

    state = state_store.load_state()
    state["driver"] = {
        "recipe_id": recipe.id,
        "package": recipe.dkms_package,
        "version": recipe.driver_version,
        "source_dir": str(source_dir),
        "firmware": firmware_files,
        "managed_by_antena": True,
        "installed_at": int(time.time()),
    }
    state_store.record_file(state, str(source_dir), f"driver:{recipe.id}")
    for item in firmware_files:
        state_store.record_file(state, item, f"driver:{recipe.id}")
    state_store.save_state(state)
    return result(
        True,
        "Controlador instalado y verificado.",
        module=probe.stdout.strip(),
        version=recipe.driver_version,
    )


def _allowed_firmware_dest(path: Path) -> bool:
    text = str(path)
    return text.startswith("/usr/lib/firmware/") or text.startswith("/lib/firmware/")


def _rollback_driver(
    source_dir: Path,
    recipe: Recipe,
    firmware_files: list[str],
    kernel: str | None,
    remove_dkms: bool,
) -> None:
    """Deshace una instalación a medias. Nunca toca paquetes del sistema."""
    if remove_dkms:
        try:
            RUNNER.run(
                ["dkms", "remove", "-m", recipe.dkms_package, "-v", recipe.driver_version, "--all"],
                timeout=300,
            )
        except Exception:
            pass
    for item in firmware_files:
        try:
            Path(item).unlink()
        except OSError:
            pass
    try:
        if source_dir.exists():
            shutil.rmtree(source_dir)
    except OSError:
        pass
    if kernel:
        RUNNER.run(["depmod", kernel], timeout=120)


def op_switch_mode(payload: dict[str, Any]) -> dict[str, Any]:
    recipe = require_recipe(payload)
    usb_path = require_usb_path(payload)
    modeswitch = recipe.modeswitch
    if not modeswitch:
        raise HelperError("no_modeswitch", "La receta no define cambio de modo.")
    targets = {str(item).lower() for item in modeswitch.get("targets", ())}
    current = next(
        (item for item in Sysfs().usb_devices() if item.path_name == usb_path),
        None,
    )
    if current is None:
        raise HelperError("device_missing", "El adaptador ya no está conectado.")
    if current.usb_id in targets:
        return result(True, "El adaptador ya está en modo operativo.", already_switched=True)
    device = verify_modeswitch_target(recipe, usb_path)
    if device.usb_id != f"{modeswitch['vid']}:{modeswitch['pid']}".lower():
        raise HelperError("identity_mismatch", "El adaptador no está en la etapa USB esperada.")
    progress("Cambiando el modo USB del adaptador…")
    args = build_modeswitch_args(recipe)
    switched = RUNNER.run(args, timeout=60)
    technical = (switched.stdout + "\n" + switched.stderr).strip()
    timeout = min(max(int(modeswitch.get("timeout_seconds", 25)), 5), 60)
    deadline = time.monotonic() + timeout
    observed = ""
    while time.monotonic() < deadline:
        sysfs = Sysfs()
        devices = sysfs.usb_devices()
        for item in devices:
            if item.usb_id in targets:
                observed = item.usb_id
                break
        if observed:
            break
        time.sleep(0.5)
    if not observed:
        raise HelperError(
            "modeswitch_timeout",
            "El adaptador no reapareció en modo operativo.",
            technical[-2000:],
        )
    return result(True, "Modo USB cambiado y reenumeración verificada.", usb_id=observed)


def op_load_modules(payload: dict[str, Any]) -> dict[str, Any]:
    recipe = require_recipe(payload)
    require_usb_path(payload)
    modules = [item for item in recipe.modules if item in ALLOWED_MODULES or item in recipe.modules]
    if not modules:
        raise HelperError("no_modules", "La receta no define módulos.")
    for module in modules:
        if not recipe.allows_module(module):
            raise HelperError("module_not_allowed", "Módulo no permitido por la receta.")
        if not re.fullmatch(r"[a-zA-Z0-9_]{1,64}", module):
            raise HelperError("module_not_allowed", "Nombre de módulo inválido.")
        progress(f"Cargando {module}…")
        loaded = RUNNER.run(["modprobe", module], timeout=120)
        if not loaded.ok:
            raise HelperError(
                "modprobe_failed",
                f"No se pudo cargar {module}.",
                (loaded.stderr or loaded.stdout).strip()[-2000:],
            )
    loaded_now = read_text(Path("/proc/modules"))
    missing = [item for item in modules if not re.search(rf"^{re.escape(item)}\s", loaded_now, re.M)]
    if missing:
        raise HelperError("verify_failed", "Los módulos no aparecen cargados.", ", ".join(missing))
    return result(True, "Controlador activado.", modules=", ".join(modules))


def op_install_persistence(payload: dict[str, Any]) -> dict[str, Any]:
    recipe = require_recipe(payload)
    usb_path = require_usb_path(payload)
    persistence = recipe.persistence
    if not persistence or not persistence.get("udev_rule"):
        raise HelperError("no_persistence", "La receta no define persistencia.")
    device = next((item for item in Sysfs().usb_devices() if item.path_name == usb_path), None)
    if device is None:
        raise HelperError("device_missing", "El adaptador no está conectado.")
    modeswitch = recipe.modeswitch or {}
    if device.usb_id not in {str(item).lower() for item in modeswitch.get("targets", ())}:
        raise HelperError("not_operational", "El adaptador no está en modo operativo.")
    if not device.net_names:
        raise HelperError(
            "no_interface",
            "El adaptador aún no tiene interfaz Wi-Fi; no se guarda la configuración.",
        )
    script = str(persistence.get("helper_script", ""))
    if not script.startswith("/usr/lib/antena/bin/"):
        raise HelperError("bad_persistence", "Ruta de script no permitida.")
    if not Path(script).is_file():
        raise HelperError("missing_script", "Falta el script de cambio de modo del paquete.")
    rule_name = str(persistence.get("udev_rule", ""))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.rules", rule_name):
        raise HelperError("bad_persistence", "Nombre de regla inválido.")
    manufacturer = next(iter(recipe.storage_requirements()["manufacturers"]), "")
    product = next(iter(recipe.storage_requirements()["products"]), "")
    if not manufacturer or not product:
        raise HelperError("bad_persistence", "La receta no define suficientes datos de identidad.")
    rule = (
        "# Managed by Antena. Do not edit; remove it with Antena or antena-helper cleanup.\n"
        'ACTION=="add", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", '
        f'ATTR{{idVendor}}=="{modeswitch["vid"]}", ATTR{{idProduct}}=="{modeswitch["pid"]}", '
        f'ATTR{{manufacturer}}=="{manufacturer}", ATTR{{product}}=="{product}", '
        f'RUN+="{script}"\n'
    )
    rule_path = MANAGED_UDEV_DIR / rule_name
    modules_path = MANAGED_MODULES_LOAD_DIR / f"antena-{recipe.id}.conf"
    state = state_store.load_state()
    owner = f"persistence:{recipe.id}"
    # Nunca se sobrescribe un archivo que Antena no haya creado.
    for target in (rule_path, modules_path):
        if target.exists() and state_store.files_for(state, owner).count(str(target)) == 0:
            raise HelperError(
                "path_conflict",
                f"Ya existe {target} y no pertenece a Antena. No se modificará.",
            )
    rule_path.parent.mkdir(parents=True, exist_ok=True)
    rule_path.write_text(rule, encoding="utf-8")
    os.chmod(rule_path, 0o644)
    state_store.record_file(state, str(rule_path), owner)
    created = [str(rule_path)]
    if persistence.get("modules_load"):
        modules_path.parent.mkdir(parents=True, exist_ok=True)
        modules_path.write_text(
            f"# Managed by Antena\n{recipe.primary_module}\n", encoding="utf-8"
        )
        os.chmod(modules_path, 0o644)
        state_store.record_file(state, str(modules_path), owner)
        created.append(str(modules_path))
    state_store.save_state(state)
    reload_cmd = RUNNER.run(["udevadm", "control", "--reload-rules"], timeout=30)
    if not reload_cmd.ok:
        raise HelperError("udev_reload_failed", "No se pudieron recargar las reglas udev.")
    return result(True, "Configuración persistente instalada.", files=", ".join(created))


def op_remove_persistence(payload: dict[str, Any]) -> dict[str, Any]:
    recipe = require_recipe(payload)
    state = state_store.load_state()
    owner = f"persistence:{recipe.id}"
    removed = _remove_owned_files(state, owner)
    state_store.save_state(state)
    RUNNER.run(["udevadm", "control", "--reload-rules"], timeout=30)
    return result(True, "Configuración persistente retirada.", removed=", ".join(removed))


def _remove_owned_files(state: dict[str, Any], owner: str) -> list[str]:
    removed: list[str] = []
    for path in state_store.files_for(state, owner):
        target = Path(path)
        try:
            if target.suffix == ".rules":
                content = target.read_text(encoding="utf-8", errors="replace")
                if MANAGED_MARKER not in content:
                    continue
            if target.is_file():
                target.unlink()
                removed.append(path)
            elif target.is_dir() and owner.startswith("driver:"):
                shutil.rmtree(target)
                removed.append(path)
            state_store.forget_file(state, path)
        except OSError:
            continue
    return removed


def op_rfkill_unblock(payload: dict[str, Any]) -> dict[str, Any]:
    phy = require_str(payload, "phy", PHY_RE)
    sysfs = Sysfs()
    entry = next(
        (item for item in sysfs.rfkill() if item.kind == "wlan" and item.name == phy),
        None,
    )
    if entry is None:
        raise HelperError("rfkill_not_found", "No hay un bloqueo rfkill para esa interfaz.")
    if entry.hard_blocked:
        raise HelperError("rfkill_hard", "La radio está bloqueada físicamente. Revisa el interruptor del equipo.")
    RUNNER.run(["rfkill", "unblock", str(entry.index)], timeout=20)
    current = next(
        (item for item in Sysfs().rfkill() if item.index == entry.index),
        None,
    )
    if current is None or current.soft_blocked:
        raise HelperError("rfkill_failed", "El bloqueo por software no se pudo quitar.")
    return result(True, "Radio desbloqueada.", phy=phy)


def op_nm_manage(payload: dict[str, Any]) -> dict[str, Any]:
    iface = require_str(payload, "iface", IFACE_RE)
    validate_iface(iface)
    progress("Permitiendo que NetworkManager gestione la interfaz…")
    done = RUNNER.run(["nmcli", "device", "set", iface, "managed", "yes"], timeout=30)
    if not done.ok:
        raise HelperError(
            "nm_failed",
            "NetworkManager no aceptó la interfaz.",
            (done.stderr or done.stdout).strip()[-2000:],
        )
    status = RUNNER.run(
        ["nmcli", "-t", "-f", "GENERAL.STATE", "device", "show", iface], timeout=10
    )
    if "unmanaged" in status.stdout:
        raise HelperError("nm_verify_failed", "NetworkManager sigue sin gestionar la interfaz.")
    return result(True, "NetworkManager gestiona la interfaz.")


def op_dkms_rebuild(payload: dict[str, Any]) -> dict[str, Any]:
    recipe = require_recipe(payload)
    if recipe.is_kernel_native or not recipe.dkms_package:
        raise HelperError("not_supported", "Esta receta no usa DKMS.")
    running = read_text(Path("/proc/sys/kernel/osrelease")) or os.uname().release
    if not (Path("/lib/modules") / running / "build").exists():
        raise HelperError("headers_missing", "Faltan los encabezados del kernel.")
    progress("Reconstruyendo el módulo con DKMS…")
    build = RUNNER.run(
        ["dkms", "build", "-m", recipe.dkms_package, "-v", recipe.driver_version, "--force"],
        timeout=1800,
    )
    if not build.ok:
        raise HelperError(
            "dkms_build_failed",
            "La compilación del módulo falló.",
            (build.stdout + "\n" + build.stderr).strip()[-4000:],
        )
    install = RUNNER.run(
        ["dkms", "install", "-m", recipe.dkms_package, "-v", recipe.driver_version, "--force"],
        timeout=600,
    )
    if not install.ok:
        raise HelperError(
            "dkms_install_failed",
            "DKMS no pudo instalar el módulo.",
            (install.stdout + "\n" + install.stderr).strip()[-4000:],
        )
    RUNNER.run(["depmod", running], timeout=120)
    return result(True, "Módulo reconstruido.")


def op_monitor_probe(payload: dict[str, Any]) -> dict[str, Any]:
    iface = require_str(payload, "iface", IFACE_RE)
    validate_iface(iface, require_disconnected=True)
    channel = payload.get("channel", 6)
    seconds = payload.get("seconds", 8)
    if not isinstance(channel, int) or not 1 <= channel <= 196:
        raise HelperError("bad_channel", "Canal fuera de rango.")
    if not isinstance(seconds, int) or not 3 <= seconds <= 15:
        raise HelperError("bad_duration", "Duración fuera de rango.")
    if not RUNNER.which("tcpdump"):
        raise HelperError("missing_dependency", "tcpdump no está instalado.")
    monitor = "antena-mon"
    if monitor in Sysfs().net_names():
        raise HelperError("monitor_exists", "Ya existe una interfaz temporal. Reconecta el adaptador.")
    created = False
    try:
        added = RUNNER.run(
            ["iw", "dev", iface, "interface", "add", monitor, "type", "monitor"], timeout=30
        )
        if not added.ok:
            raise HelperError(
                "monitor_failed",
                "El controlador no pudo crear la interfaz monitor.",
                (added.stderr or added.stdout).strip()[-2000:],
            )
        created = True
        RUNNER.run(["ip", "link", "set", monitor, "up"], timeout=20)
        channel_cmd = RUNNER.run(["iw", "dev", monitor, "set", "channel", str(channel)], timeout=20)
        if not channel_cmd.ok:
            raise HelperError(
                "channel_failed",
                "No se pudo fijar el canal del modo monitor.",
                (channel_cmd.stderr or channel_cmd.stdout).strip()[-2000:],
            )
        handle, pcap_path = tempfile.mkstemp(prefix="antena-monitor-", suffix=".pcap", dir="/var/tmp")
        os.close(handle)
        try:
            progress("Escuchando tramas Beacon…")
            capture = RUNNER.run(
                [
                    "timeout",
                    str(seconds),
                    "tcpdump",
                    "-i",
                    monitor,
                    "-w",
                    pcap_path,
                    "-c",
                    "200",
                    "-s",
                    "256",
                    "type mgt subtype beacon",
                ],
                timeout=seconds + 10,
            )
            if capture.returncode not in (0, 124):
                raise HelperError(
                    "capture_failed",
                    "No se pudo capturar en modo monitor.",
                    (capture.stderr or capture.stdout).strip()[-2000:],
                )
            counts = count_beacons(Path(pcap_path))
        finally:
            try:
                Path(pcap_path).unlink()
            except OSError:
                pass
    finally:
        if created:
            RUNNER.run(["ip", "link", "set", monitor, "down"], timeout=15)
            RUNNER.run(["iw", "dev", monitor, "del"], timeout=15)
    if counts["packets"] == 0:
        return result(
            True,
            "La prueba terminó, pero no se recibieron Beacons.",
            packets=0,
            beacons=0,
        )
    return result(
        True,
        "Recepción pasiva verificada.",
        packets=counts["packets"],
        beacons=counts["beacons"],
    )


def op_cleanup(payload: dict[str, Any]) -> dict[str, Any]:
    """Retira solo lo que Antena creó.

    Por defecto nunca toca controladores: son componentes de terceros y su
    retirada exige consentimiento explícito (remove_driver=true).
    """
    state = state_store.load_state()
    removed: list[str] = []
    persistence_owners = {
        value for value in state.get("files", {}).values() if str(value).startswith("persistence:")
    }
    for owner in sorted(persistence_owners):
        removed.extend(_remove_owned_files(state, owner))
    driver = state.get("driver")
    driver_removed = False
    if payload.get("remove_driver") is True and isinstance(driver, dict) and driver.get("managed_by_antena"):
        package = str(driver.get("package", ""))
        version = str(driver.get("version", ""))
        if package and version:
            RUNNER.run(["dkms", "remove", "-m", package, "-v", version, "--all"], timeout=600)
            removed.extend(_remove_owned_files(state, f"driver:{driver.get('recipe_id', '')}"))
            state["driver"] = None
            driver_removed = True
    state_store.save_state(state)
    RUNNER.run(["udevadm", "control", "--reload-rules"], timeout=30)
    return result(
        True,
        "Limpieza completada.",
        removed=", ".join(sorted(set(removed))),
        driver_removed=driver_removed,
    )


OPERATIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "install_packages": op_install_packages,
    "install_driver": op_install_driver,
    "switch_mode": op_switch_mode,
    "load_modules": op_load_modules,
    "install_persistence": op_install_persistence,
    "remove_persistence": op_remove_persistence,
    "rfkill_unblock": op_rfkill_unblock,
    "nm_manage": op_nm_manage,
    "dkms_rebuild": op_dkms_rebuild,
    "monitor_probe": op_monitor_probe,
    "cleanup": op_cleanup,
}


def dispatch(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    handler = OPERATIONS.get(operation)
    if handler is None:
        raise HelperError("unknown_operation", "Operación no permitida.")
    return handler(payload)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        emit(result(False, "Uso: antena-helper <operación> (JSON por stdin).", code="usage"))
        return 2
    if args[0] == "--version":
        emit(result(True, VERSION))
        return 0
    if os.geteuid() != 0:
        emit(result(False, "Se requiere autorización de administrador.", code="not_root"))
        return 3
    # Entorno mínimo y predecible para binarios del sistema.
    os.environ["PATH"] = "/usr/sbin:/usr/bin:/sbin:/bin"
    operation = args[0]
    try:
        raw = sys.stdin.read(MAX_PAYLOAD + 1)
        if len(raw) > MAX_PAYLOAD:
            raise HelperError("bad_payload", "El payload es demasiado grande.")
        payload = validate_payload(json.loads(raw) if raw.strip() else {})
        final = dispatch(operation, payload)
    except HelperError as exc:
        final = result(False, exc.message, exc.technical, code=exc.code)
    except json.JSONDecodeError:
        final = result(False, "JSON inválido.", code="bad_json")
    except Exception as exc:  # nunca exponer trazas al usuario
        final = result(False, "Error interno del componente privilegiado.", type(exc).__name__, code="internal")
    emit(final)
    return 0 if final.get("ok") else 4


if __name__ == "__main__":
    raise SystemExit(main())
