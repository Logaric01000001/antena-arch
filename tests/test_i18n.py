"""Idiomas y catálogo: consistencia y trazabilidad."""

from __future__ import annotations

from pathlib import Path

from antena.core.catalog import load_recipes
from antena.i18n import EN, ES, TABLES, set_language, t


def test_language_tables_have_identical_keys():
    assert set(ES) == set(EN)
    assert all(ES[key] for key in ES)
    assert all(EN[key] for key in EN)


def test_spanish_and_english_render_placeholders():
    set_language("es")
    assert "redes" in t("scan.count", count=3)
    set_language("en")
    assert "networks" in t("scan.count", count=3)
    set_language("es")


def test_all_catalog_recipes_validate():
    recipes = load_recipes(Path(__file__).resolve().parent.parent / "antena" / "catalog")
    assert len(recipes) >= 7
    ids = {recipe.id for recipe in recipes}
    assert "aic8800d80" in ids
    aic = next(item for item in recipes if item.id == "aic8800d80")
    assert aic.modules == ("aic_load_fw", "aic8800_fdrv")
    assert aic.source["sha256"] == "fbb3d8e912a9ce80847bd26c5615337d1f968c9297f7e28ae7209c7519772b28"
    assert aic.tested_kernels == ("7.2.11-arch1-1",)
    assert "packet_injection" in aic.unverified_capabilities


def test_translation_keys_used_by_recipes_exist():
    recipes = load_recipes(Path(__file__).resolve().parent.parent / "antena" / "catalog")
    missing = []
    for recipe in recipes:
        keys = [recipe.summary_key]
        note = recipe.capabilities.get("note_key")
        if note:
            keys.append(note)
        for key in keys:
            if key and key not in TABLES["es"]:
                missing.append(key)
    assert missing == []
