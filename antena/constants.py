"""Constantes compartidas por la aplicación y el helper privilegiado."""

from __future__ import annotations

import os
from pathlib import Path

APP_ID = "io.github.antena.Antena"
APP_NAME = "Antena"
VERSION = "0.1.0"

# Marcador deliberado: sustituir por la URL real antes de publicar.
PROJECT_URL = "https://github.com/USUARIO/antena-arch"
LICENSE_NAME = "GPL-3.0-or-later"

# Rutas de instalación del paquete.
PREFIX_LIB = Path("/usr/lib/antena")
INSTALLED_CATALOG = Path("/usr/share/antena/catalog")
INSTALLED_HELPER = PREFIX_LIB / "antena-helper"
HELPER_SCRIPT_SOURCE = PREFIX_LIB / "bin" / "antena-helper"

# Estado del sistema escrito por el helper (solo root).
SYSTEM_STATE_DIR = Path("/var/lib/antena")
SYSTEM_STATE_FILE = SYSTEM_STATE_DIR / "state.json"
SYSTEM_LOG_FILE = SYSTEM_STATE_DIR / "events.jsonl"

# Rutas que Antena puede crear y por tanto puede retirar.
MANAGED_UDEV_DIR = Path("/etc/udev/rules.d")
MANAGED_MODULES_LOAD_DIR = Path("/etc/modules-load.d")
MANAGED_USB_MODESWITCH_DIR = Path("/etc/usb_modeswitch.d")

# Dependencias que el helper puede instalar desde los repositorios oficiales.
ALLOWED_PACMAN_PACKAGES = frozenset(
    {
        "dkms",
        "usb_modeswitch",
        "linux-headers",
        "linux-lts-headers",
        "linux-zen-headers",
        "linux-hardened-headers",
        "linux-cachyos-headers",
        "linux-firmware",
        "iw",
        "tcpdump",
    }
)

# Módulos que el helper puede cargar. El catálogo puede ampliar esta lista
# únicamente mediante recetas revisadas; nunca desde la interfaz.
ALLOWED_MODULES = frozenset({"aic_load_fw", "aic8800_fdrv"})


def catalog_dir() -> Path:
    """Devuelve el catálogo instalado o el del repositorio durante el desarrollo."""
    override = os.environ.get("ANTENA_CATALOG_DIR")
    if override:
        return Path(override)
    if INSTALLED_CATALOG.is_dir():
        return INSTALLED_CATALOG
    return Path(__file__).resolve().parent / "catalog"


def user_state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        return Path(base) / "antena"
    return Path.home() / ".local" / "state" / "antena"


def helper_path() -> Path | None:
    override = os.environ.get("ANTENA_HELPER")
    if override:
        path = Path(override)
        return path if path.is_file() else None
    if INSTALLED_HELPER.is_file():
        return INSTALLED_HELPER
    return None
