# Añadir un dispositivo

## Requisitos

Una receta nueva se acepta si cumple **todo** esto:

1. Hay hardware real para probarla.
2. Se conoce el chipset y la etapa USB, no solo el VID:PID.
3. El controlador tiene fuente, versión y licencia trazables.
4. Si hay descarga, está fijada por SHA-256 y tamaño.
5. El procedimiento se ha ejecutado al menos una vez en un kernel concreto.
6. Existen comprobaciones de éxito objetivas (módulo, interfaz, escaneo).
7. Se documentan fallos conocidos y recuperación.
8. Hay pruebas para identificación, estados de error e idempotencia.

No se aceptan recetas “porque el chipset debería funcionar” ni controladores
copiados de otro modelo. Antena prefiere decir “no compatible”.

## Estructura de una receta

Cada archivo vive en `antena/catalog/<id>.json` y se valida al cargar.

```json
{
  "schema": 1,
  "id": "vendor-chipset",
  "name": "Nombre legible",
  "vendor": "Fabricante",
  "family": "Familia",
  "summary_key": "recipe.vendor_chipset.summary",
  "match": {
    "usb_ids": ["1234:5678"],
    "manufacturers": ["Vendor"],
    "products": ["Modelo"],
    "storage_ids": ["1111:1111"],
    "drivers": ["module_name"]
  },
  "usb_stages": {
    "storage": ["1111:1111"],
    "transitional": ["1234:5679"],
    "operational": ["1234:5678"]
  },
  "driver": {
    "kind": "dkms",
    "package": "paquete-dkms",
    "dkms_package": "paquete-dkms",
    "version": "1.0.0",
    "modules": ["module_a", "module_b"],
    "primary_module": "module_b",
    "license": "GPL-2.0-only",
    "upstream": "https://…",
    "source_url": "https://…/release.tar.gz",
    "source_sha256": "64 caracteres hex",
    "source_size": 123456,
    "source_version": "1.0.0",
    "source_pkgrel": 1,
    "source_root": "carpeta-extraida",
    "dkms_files": ["ruta/Makefile", "ruta/dkms.conf"],
    "firmware": { "source": "fw", "dest": "/usr/lib/firmware/foo" },
    "pacman_dependencies": ["dkms"],
    "tested_kernels": ["7.2.11-arch1-1"],
    "tested_date": "2026-10-24"
  },
  "modeswitch": {
    "vid": "1111",
    "pid": "1111",
    "message": "hex",
    "message2": "hex",
    "targets": ["1234:5678"],
    "timeout_seconds": 25,
    "require_storage_class": true,
    "require_manufacturer": ["Vendor"],
    "require_product": ["Modelo"]
  },
  "persistence": {
    "udev_rule": "99-antena-foo.rules",
    "helper_script": "/usr/lib/antena/bin/antena-modeswitch-foo",
    "modules_load": true
  },
  "verification": {
    "interface_required": true,
    "scan": true,
    "allowed_modules": ["module_a", "module_b"]
  },
  "capabilities": {
    "verified": ["scan_2ghz"],
    "unverified": ["packet_injection"],
    "driver_advertised": ["managed", "monitor"],
    "note_key": "recipe.vendor_chipset.capability_note"
  },
  "sources": ["https://…"]
}
```

### Campos delicados

- `storage_ids`: IDs compartidos por varios dispositivos. Nunca se aceptan sin
  producto o fabricante; el código lo impone.
- `source_sha256` y `source_size`: obligatorios si hay `source_url`.
- `persistence.helper_script`: debe empezar por `/usr/lib/antena/bin/` y existir.
- `persistence.udev_rule`: solo nombre de archivo `.rules`, sin rutas.
- `capabilities.verified`: solo lo probado en hardware real. Si no lo probaste,
  va en `unverified`.
- `tested_kernels`: no inventes; si no hay prueba, deja la lista vacía y no
  uses una receta DKMS.

## Pasos

1. Copia `antena/catalog/kernel-mt7601u.json` como base mínima o
   `aic8800d80.json` si hay cambio de modo.
2. Añade los textos a `antena/i18n.py` (`recipe.<id>.summary`, notas).
3. Añade la receta y valida:

   ```bash
   PYTHONPATH=. python3 -c "from antena.core.catalog import load_recipes; print(load_recipes())"
   ```

4. Añade pruebas en `tests/`:
   - detección con VID/PID y producto correctos;
   - ID de almacenamiento sin producto → no debe coincidir;
   - etapa operativa y interfaz;
   - driver ausente → plan de instalación;
   - headers/DKMS fallidos → acciones;
   - desconexión/cancelación;
   - conflicto con otro paquete.

5. Si hay `usb_modeswitch`, añade el script fijo en `antena/bin/` y el paquete
   debe instalarlo. El script no acepta argumentos.
6. Ejecuta la suite y `makepkg -f`.
7. Documenta en `docs/DRIVERS.md` qué está verificado y qué no.
8. Envía el PR indicando hardware, kernel, comandos observados y resultados.
   Adjunta `antena --diagnose --json` sin datos personales.

## Lo que no se acepta

- Controladores descargados de enlaces cambiantes sin hash.
- `curl | bash`, scripts remotos, `shell=True`.
- Añadir repositorios con `SigLevel = TrustAll`.
- Reglas udev genéricas por VID/PID cuando el ID es compartido.
- Desinstalar o sobrescribir controladores existentes sin diagnóstico.
- Anunciar inyección de paquetes o ataques.
- Recetas sin evidencia de hardware.
