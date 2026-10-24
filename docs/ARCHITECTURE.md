# Arquitectura

## Principio

Una interfaz que no sabe nada de drivers; un núcleo que no sabe nada de GTK; un
helper que no acepta comandos. Cada capa se puede probar por separado.

```
┌─────────────────────────────────────────────────────────────┐
│ antena/ui/*          GTK4 + libadwaita (usuario, sin root)  │
│   window, pages, repair, widgets, i18n                      │
└───────────────┬─────────────────────────────────────────────┘
                │ Detector / Diagnostics / Plan / Executor
┌───────────────▼─────────────────────────────────────────────┐
│ antena/core/*        lógica pura y lectura del sistema      │
│   detect, catalog, diagnose, planner, executor, report      │
│   sysfs, network, drivers, runner (sin shell)               │
└───────────────┬─────────────────────────────────────────────┘
                │ pkexec + JSON por stdin, operaciones cerradas
┌───────────────▼─────────────────────────────────────────────┐
│ antena/priv/*        helper root de vida corta              │
│   helper (allowlist), state, pcap                           │
└───────────────┬─────────────────────────────────────────────┘
                │
        sysfs · udev · NetworkManager · iw · rfkill
        modinfo · DKMS · pacman · usb_modeswitch
```

## Capas

| Capa | Responsabilidad | No hace |
|---|---|---|
| `ui` | Presentar estados, recoger decisiones, mostrar progreso | Leer sysfs con privilegios, ejecutar cambios |
| `core.detect` | Enumerar USB/PCI, mapear interfaces, módulos y catálogo | Modificar nada |
| `core.catalog` | Validar y servir recetas | Depender de la GUI |
| `core.diagnose` | Comprobaciones independientes y acciones propuestas | Ejecutar reparaciones |
| `core.planner` | Orden seguro de etapas e idempotencia | Inventar éxito |
| `core.executor` | Ejecutar y **verificar** cada etapa; cancelar | Ocultar fallos |
| `core.privileged` | Hablar con el helper por `pkexec` | Ejecutar shell |
| `priv.helper` | Cambios concretos, revalidación, rollback | Aceptar comandos o paquetes arbitrarios |
| `priv.state` | Registro de archivos propios | Borrar archivos ajenos |

## Detección

1. `Sysfs.usb_devices()` recorre `/sys/bus/usb/devices`, excluye root hubs y
   directorios de interfaz, y lee descriptores, clases, interfaces, netdevs y
   el driver de cada interfaz USB.
2. Para cada interfaz de red, `NetworkTools` consulta `nmcli` e `iw` y
   `Sysfs` resuelve PHY, MAC y rfkill.
3. `DriverInspector` consulta `/proc/modules`, `modinfo`, `/lib/modules/*/modules.alias`,
   `dkms status` y `pacman -Q`.
4. `_match_recipe` puntúa coincidencia por USB ID, fabricante, producto y
   driver. Un ID de la etapa de almacenamiento (`1111:1111`) **nunca basta**:
   exige también producto o fabricante.
5. El resultado es un `DeviceInfo` con estado y razones explícitas. La interfaz
   solo traduce esas razones; no deduce estados.

### Estados

```
storage ──(modeswitch)──► transitional ──(reenumeración)──► operational
                                                               │
                                          driver + interfaz + rfkill + NM
                                                               ▼
                                                             READY
```

`NEEDS_SETUP` = falta un paso seguro y conocido.
`NEEDS_ATTENTION` = hay algo que impide confirmar el funcionamiento.
`UNSUPPORTED` = chipset sin receta; solo diagnóstico.
`READY` = driver cargado, interfaz presente, sin bloqueo y gestionada.

La interfaz distingue además capacidades **verificadas** (receta probada en
hardware), **anunciadas** (modos que declara el driver) y **no verificadas**
(p. ej. inyección de paquetes).

## Planes y ejecución

`PlanStage` es una unidad con `op`, `payload` y clave de traducción. Las
operaciones locales (`local:*`) viven en el ejecutor; las privilegiadas
(`priv:*`) van al helper. Antes de cada etapa privilegiada se comprueba si ya
está hecha (idempotencia). Después se vuelve a detectar y se verifica el
resultado; si el helper dice `ok` pero la verificación falla, la etapa falla.

Orden típico de configuración:

1. comprobar entorno;
2. instalar dependencias/encabezados si faltan;
3. instalar driver DKMS si no existe para el kernel;
4. cambiar modo USB si está en almacenamiento;
5. cargar módulos;
6. esperar y verificar la interfaz;
7. escanear redes de verdad;
8. instalar persistencia solo si el dispositivo está operativo;
9. verificar estado final.

La cancelación se propaga entre etapas y al proceso `pkexec`; una cancelación
nunca se presenta como éxito.

## Frontera de seguridad

El helper solo conoce estas operaciones:

| Operación | Efecto | Validaciones |
|---|---|---|
| `install_packages` | `pacman -S` | lista cerrada de paquetes |
| `install_driver` | descarga + DKMS + firmware | receta, hash, tamaño, tar seguro, headers, conflicto |
| `switch_mode` | `usb_modeswitch` | VID/PID/clase/fabricante/producto reales |
| `load_modules` | `modprobe` | módulos de la receta |
| `install_persistence` | udev + modules-load | dispositivo operativo, rutas propias, no sobrescribir |
| `remove_persistence` | borra archivos propios | solo registro de estado y marca |
| `rfkill_unblock` | `rfkill unblock <idx>` | PHY wifi real, sin bloqueo duro |
| `nm_manage` | `nmcli device set managed` | interfaz wifi real |
| `dkms_rebuild` | DKMS build/install | receta DKMS, headers |
| `monitor_probe` | interfaz monitor temporal | interfaz desconectada, canal, duración, limpieza |
| `cleanup` | retira persistencia | nunca controladores sin `remove_driver: true` |

No hay operación que reciba una cadena de comando, una URL arbitraria, un
nombre de paquete arbitrario ni una ruta de escritura arbitraria.

## Persistencia y desinstalación

`/var/lib/antena/state.json` registra propietario y ruta de cada archivo creado.
La instalación de persistencia se niega si el archivo existe y no está
registrado. La limpieza:

- retira solo archivos con propietario `persistence:*`;
- verifica la marca `Managed by Antena` en reglas udev;
- no toca paquetes, firmware ni controladores ajenos;
- solo retira el driver si el estado dice `managed_by_antena` **y** se envía
  `{"remove_driver": true}`.

## Pruebas

`tests/fakeenv.py` construye un sysfs completo en `tmp_path`, con USB, PHY,
rfkill, módulos, DKMS y paquetes simulados. `FakeRunner` responde a comandos
por prefijo y registra llamadas. Esto permite comprobar detección, diagnóstico,
planes, cancelación, desconexión y limpieza sin hardware.

Las pruebas de GUI no forman parte de la suite automática porque requieren
sesión gráfica; se verificaron manualmente en Wayland/Niri y en Xvfb con
capturas reales. La lógica de presentación es fina y delega en `core`.

## Empaquetado

- `PKGBUILD` raíz: construcción local desde el repositorio (`$startdir`).
- `packaging/PKGBUILD.aur`: plantilla para el tag publicado; no está activa.
- Launchers en `/usr/bin/antena` y `/usr/lib/antena/antena-helper`.
- Catálogo instalado en `/usr/share/antena/catalog`.
- Iconos, `.desktop` y metainfo AppStream propios.
- `pre_remove` ejecuta la limpieza de persistencia; nunca la del driver.
