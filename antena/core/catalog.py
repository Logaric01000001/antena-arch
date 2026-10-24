"""Catálogo de recetas de dispositivo, desacoplado de la interfaz."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from antena.core.models import Confidence, UsbRecord, UsbStage

USB_ID_RE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CatalogError(RuntimeError):
    pass


def _require(mapping: dict[str, Any], key: str, kind: type | tuple[type, ...] = object) -> Any:
    value = mapping.get(key)
    if not isinstance(value, kind):
        raise CatalogError(f"campo '{key}' inválido o ausente")
    return value


@dataclass(frozen=True)
class Recipe:
    raw: dict[str, Any]

    # -- identidad ------------------------------------------------------
    @property
    def id(self) -> str:
        return str(self.raw["id"])

    @property
    def name(self) -> str:
        return str(self.raw["name"])

    @property
    def vendor(self) -> str:
        return str(self.raw.get("vendor", ""))

    @property
    def family(self) -> str:
        return str(self.raw.get("family", ""))

    @property
    def summary_key(self) -> str:
        return str(self.raw.get("summary_key", ""))

    # -- coincidencia ---------------------------------------------------
    @property
    def match(self) -> dict[str, Any]:
        return self.raw.get("match", {})

    @property
    def usb_ids(self) -> tuple[str, ...]:
        return tuple(item.lower() for item in self.match.get("usb_ids", ()))

    @property
    def storage_ids(self) -> tuple[str, ...]:
        return tuple(item.lower() for item in self.match.get("storage_ids", ()))

    @property
    def drivers(self) -> tuple[str, ...]:
        return tuple(self.match.get("drivers", ()))

    @property
    def manufacturers(self) -> tuple[str, ...]:
        return tuple(item.lower() for item in self.match.get("manufacturers", ()))

    @property
    def products(self) -> tuple[str, ...]:
        return tuple(item.lower() for item in self.match.get("products", ()))

    # -- driver ---------------------------------------------------------
    @property
    def driver(self) -> dict[str, Any]:
        return self.raw.get("driver", {})

    @property
    def driver_kind(self) -> str:
        return str(self.driver.get("kind", "kernel"))

    @property
    def is_kernel_native(self) -> bool:
        return self.driver_kind == "kernel"

    @property
    def package(self) -> str:
        return str(self.driver.get("package", ""))

    @property
    def dkms_package(self) -> str:
        return str(self.driver.get("dkms_package", ""))

    @property
    def driver_version(self) -> str:
        return str(self.driver.get("version", ""))

    @property
    def modules(self) -> tuple[str, ...]:
        return tuple(self.driver.get("modules", ()))

    @property
    def primary_module(self) -> str:
        return str(self.driver.get("primary_module", self.modules[0] if self.modules else ""))

    @property
    def firmware_dest(self) -> str:
        firmware = self.driver.get("firmware", {})
        return str(firmware.get("dest") or "") if isinstance(firmware, dict) else ""

    @property
    def tested_kernels(self) -> tuple[str, ...]:
        return tuple(self.driver.get("tested_kernels", ()))

    @property
    def source(self) -> dict[str, Any]:
        value = self.driver.get("source_url")
        if not value:
            return {}
        return {
            "url": str(value),
            "sha256": str(self.driver.get("source_sha256", "")),
            "size": int(self.driver.get("source_size", 0)),
            "version": str(self.driver.get("source_version", "")),
            "pkgrel": int(self.driver.get("source_pkgrel", 0)),
            "root": str(self.driver.get("source_root", "")),
            "dkms_files": tuple(self.driver.get("dkms_files", ())),
            "firmware_source": str(self.driver.get("firmware", {}).get("source", "")),
            "firmware_dest": self.firmware_dest,
        }

    # -- operaciones ----------------------------------------------------
    @property
    def modeswitch(self) -> dict[str, Any] | None:
        value = self.raw.get("modeswitch")
        return value if isinstance(value, dict) else None

    @property
    def persistence(self) -> dict[str, Any]:
        value = self.raw.get("persistence", {})
        return value if isinstance(value, dict) else {}

    @property
    def verification(self) -> dict[str, Any]:
        value = self.raw.get("verification", {})
        return value if isinstance(value, dict) else {}

    @property
    def capabilities(self) -> dict[str, Any]:
        value = self.raw.get("capabilities", {})
        return value if isinstance(value, dict) else {}

    @property
    def verified_capabilities(self) -> tuple[str, ...]:
        return tuple(self.capabilities.get("verified", ()))

    @property
    def unverified_capabilities(self) -> tuple[str, ...]:
        return tuple(self.capabilities.get("unverified", ()))

    @property
    def advertised_modes(self) -> tuple[str, ...]:
        return tuple(self.capabilities.get("driver_advertised", ()))

    # -- lógica ---------------------------------------------------------
    def stage_for(self, usb_id: str) -> UsbStage:
        stages = self.raw.get("usb_stages", {})
        lowered = usb_id.lower()
        for name, ids in stages.items():
            if lowered in {str(item).lower() for item in ids}:
                return {
                    "storage": UsbStage.STORAGE,
                    "transitional": UsbStage.TRANSITIONAL,
                    "operational": UsbStage.OPERATIONAL,
                }.get(name, UsbStage.UNKNOWN)
        return UsbStage.UNKNOWN

    def match_confidence(self, usb: UsbRecord, driver_module: str = "") -> Confidence:
        product = usb.product.lower()
        manufacturer = usb.manufacturer.lower()
        id_match = usb.usb_id in self.usb_ids
        product_match = any(item in product for item in self.products) if self.products else False
        manufacturer_match = (
            any(item in manufacturer for item in self.manufacturers) if self.manufacturers else False
        )
        driver_match = bool(driver_module and driver_module in self.drivers)
        # Un identificador de la etapa de almacenamiento (1111:1111) se
        # comparte entre dispositivos muy distintos: nunca basta por sí solo.
        if id_match and usb.usb_id in self.storage_ids and not (
            product_match or manufacturer_match
        ):
            return Confidence.NONE
        if driver_match and (id_match or product_match):
            return Confidence.CONFIRMED
        if id_match and (product_match or manufacturer_match):
            return Confidence.CONFIRMED
        if id_match:
            return Confidence.LIKELY
        if product_match and manufacturer_match:
            return Confidence.CONFIRMED
        if product_match or driver_match:
            return Confidence.WEAK
        return Confidence.NONE

    def matches_usb(self, usb: UsbRecord, driver_module: str = "") -> bool:
        return self.match_confidence(usb, driver_module) is not Confidence.NONE

    def matches_driver(self, module: str) -> bool:
        return bool(module and module in self.drivers)

    def storage_requirements(self) -> dict[str, Any]:
        modeswitch = self.modeswitch or {}
        return {
            "require_storage_class": bool(modeswitch.get("require_storage_class", False)),
            "manufacturers": tuple(item.lower() for item in modeswitch.get("require_manufacturer", ())),
            "products": tuple(item.lower() for item in modeswitch.get("require_product", ())),
        }

    def allows_module(self, module: str) -> bool:
        return module in set(self.verification.get("allowed_modules", ())) or module in self.modules


def _validate(data: dict[str, Any], source: Path) -> None:
    if data.get("schema") != 1:
        raise CatalogError(f"{source.name}: esquema no soportado")
    _require(data, "id", str)
    _require(data, "name", str)
    _require(data, "match", dict)
    match = data["match"]
    usb_ids = match.get("usb_ids", [])
    if not isinstance(usb_ids, list):
        raise CatalogError(f"{source.name}: usb_ids debe ser una lista")
    for usb_id in usb_ids:
        if not isinstance(usb_id, str) or not USB_ID_RE.match(usb_id.lower()):
            raise CatalogError(f"{source.name}: USB ID inválido {usb_id!r}")
    for key in ("storage_ids",):
        for usb_id in match.get(key, ()):
            if not USB_ID_RE.match(str(usb_id).lower()):
                raise CatalogError(f"{source.name}: {key} inválido {usb_id!r}")
    driver = data.get("driver", {})
    if not isinstance(driver, dict):
        raise CatalogError(f"{source.name}: driver inválido")
    if driver.get("kind") not in {"kernel", "dkms"}:
        raise CatalogError(f"{source.name}: tipo de driver no soportado")
    modules = driver.get("modules", [])
    if not isinstance(modules, list) or not all(isinstance(item, str) for item in modules):
        raise CatalogError(f"{source.name}: modules inválido")
    if driver.get("source_url"):
        sha = str(driver.get("source_sha256", ""))
        if not SHA256_RE.match(sha):
            raise CatalogError(f"{source.name}: source_sha256 inválido")
        root = str(driver.get("source_root", ""))
        if not root or "/" in root or ".." in root:
            raise CatalogError(f"{source.name}: source_root inválido")
        for relative in driver.get("dkms_files", ()):
            parts = PurePosixPath(str(relative)).parts
            if not parts or str(relative).startswith("/") or ".." in parts:
                raise CatalogError(f"{source.name}: dkms_files con ruta insegura")
        firmware = driver.get("firmware", {})
        if isinstance(firmware, dict):
            dest = str(firmware.get("dest", ""))
            if (
                dest
                and dest not in {"/usr/lib/firmware", "/lib/firmware"}
                and not (
                    dest.startswith("/usr/lib/firmware/")
                    or dest.startswith("/lib/firmware/")
                )
            ):
                raise CatalogError(f"{source.name}: destino de firmware no permitido")
            origin = str(firmware.get("source", "") or "")
            if origin and (".." in PurePosixPath(origin).parts or origin.startswith("/")):
                raise CatalogError(f"{source.name}: origen de firmware no permitido")
    modeswitch = data.get("modeswitch")
    if modeswitch:
        if not isinstance(modeswitch, dict):
            raise CatalogError(f"{source.name}: modeswitch inválido")
        for key in ("vid", "pid", "message"):
            if not isinstance(modeswitch.get(key), str) or not modeswitch.get(key):
                raise CatalogError(f"{source.name}: modeswitch.{key} inválido")
        if not re.match(r"^[0-9a-fA-F]{4}$", str(modeswitch["vid"])):
            raise CatalogError(f"{source.name}: modeswitch.vid inválido")
        if not re.match(r"^[0-9a-fA-F]{4}$", str(modeswitch["pid"])):
            raise CatalogError(f"{source.name}: modeswitch.pid inválido")
        message = str(modeswitch["message"])
        if not re.match(r"^[0-9a-fA-F]+$", message) or len(message) < 16:
            raise CatalogError(f"{source.name}: mensaje de modeswitch inválido")
        for key in ("require_manufacturer", "require_product"):
            for value in modeswitch.get(key, ()):
                if not re.fullmatch(r"[A-Za-z0-9 ._+-]{1,64}", str(value)):
                    raise CatalogError(f"{source.name}: {key} contiene caracteres no permitidos")
    persistence = data.get("persistence", {})
    if persistence:
        rule = str(persistence.get("udev_rule", ""))
        if rule and (not rule.endswith(".rules") or "/" in rule):
            raise CatalogError(f"{source.name}: nombre de regla udev inválido")
        script = str(persistence.get("helper_script", ""))
        if script and not script.startswith("/usr/lib/antena/bin/"):
            raise CatalogError(f"{source.name}: ruta de script de persistencia inválida")


def load_recipes(directory: Path | None = None) -> tuple[Recipe, ...]:
    from antena.constants import catalog_dir

    base = directory or catalog_dir()
    if not base.is_dir():
        raise CatalogError(f"catálogo no encontrado: {base}")
    recipes: list[Recipe] = []
    seen: set[str] = set()
    for path in sorted(base.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogError(f"{path.name}: {exc}") from exc
        if not isinstance(data, dict):
            raise CatalogError(f"{path.name}: la receta debe ser un objeto")
        _validate(data, path)
        if data["id"] in seen:
            raise CatalogError(f"receta duplicada: {data['id']}")
        seen.add(data["id"])
        recipes.append(Recipe(data))
    return tuple(recipes)


def find_recipe(recipes: tuple[Recipe, ...], recipe_id: str) -> Recipe | None:
    for recipe in recipes:
        if recipe.id == recipe_id:
            return recipe
    return None
