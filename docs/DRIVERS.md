# Controladores

## Política

Antena solo instala un controlador cuando existe una **receta verificada** con:

1. identidad de hardware suficiente (no solo un VID:PID genérico);
2. fuente y versión concretas;
3. licencia compatible y trazable;
4. hash SHA-256 si hay descarga;
5. procedimiento de compilación y carga probado;
6. comprobaciones de éxito reales;
7. diagnóstico y recuperación.

Para chipsets con controlador en el kernel, Antena **no instala nada**: detecta
el módulo, comprueba firmware, interfaz y estado, y ofrece diagnóstico. Eso no
equivale a haber probado ese modelo concreto.

## AIC8800D80 (verificado)

Hardware de referencia: AX900 Wi-Fi 6 USB, familia AIC8800D80 / 88M80.

| Dato | Valor |
|---|---|
| USB inicial | `1111:1111`, clase almacenamiento, producto `88M80` |
| USB transición | `a69c:8d80` |
| USB operativo | `a69c:8d83` |
| Kernel de la prueba | `7.2.11-arch1-1` |
| Controlador | `aic8800-fdrv-dkms` 6.4.3.0 |
| Módulos | `aic_load_fw`, `aic8800_fdrv` |
| Firmware | `/usr/lib/firmware/aic8800D80` |
| Origen | https://github.com/ronnyf/AIC8800-Linux-Driver |
| Licencia | GPL-2.0-only |
| Tarball | `AIC8800-Linux-Driver-6.4.3.0-8.tar.gz` |
| SHA-256 | `fbb3d8e912a9ce80847bd26c5615337d1f968c9297f7e28ae7209c7519772b28` |
| Tamaño | 1 305 156 bytes |

### Por qué no se usa AUR

El paquete `aic8800-fdrv-dkms` que funcionó en la prueba **ya no está en AUR**
(HTTP 404 en octubre de 2026). Existen alternativas mantenidas por terceros
(`aic8800d80-dkms`, `aic8800d80-wifi-bt-git-dkms`, `radxa-aic8800-usb-dkms`,
etc.), pero no se han validado con este adaptador y este kernel. Antena no
instala paquetes AUR no verificados ni ejecuta helpers de AUR como root.

En su lugar, el helper descarga el tarball del release oficial, comprueba su
hash y tamaño, extrae solo archivos regulares, construye con DKMS y verifica el
módulo resultante. La receta no redistribuye el código del controlador.

### Secuencia USB

```
1111:1111 (almacenamiento)
   │  usb_modeswitch -v 1111 -p 1111 -M <msg> -2 <msg2>
   ▼
a69c:8d80 (transición)
   │  reenumeración
   ▼
a69c:8d83 (operativo)
   │  aic8800_fdrv + firmware
   ▼
interfaz wlanN
```

Los mensajes están fijados en el catálogo y en el script udev del paquete. La
regla persistente exige VID/PID **y** fabricante `AIC` **y** producto `88M80`
para no actuar sobre otro hardware que comparta `1111:1111`.

### Capacidades

Verificadas en hardware real:

- escaneo 2,4 GHz;
- escaneo 5 GHz;
- modo monitor;
- captura pasiva de Beacons con Radiotap, sin descartes en la prueba original.

No verificadas y por tanto no anunciadas como soportadas:

- inyección de paquetes.

### Persistencia

Antena puede crear:

- `/etc/udev/rules.d/99-antena-aic8800d80.rules` — regla específica que llama
  al script fijo;
- `/etc/modules-load.d/antena-aic8800d80.conf` — carga temprana de
  `aic8800_fdrv`.

El script `/usr/lib/antena/bin/antena-modeswitch-aic8800d80` viene del paquete
y contiene los mensajes constantes. No acepta argumentos. La persistencia no se
instala hasta que el dispositivo está operativo y la interfaz existe.

## Controladores nativos detectados

| Receta | Driver | Notas |
|---|---|---|
| `kernel-ath9k-htc` | `ath9k_htc` | AR9271; firmware de `linux-firmware` |
| `kernel-rt2800usb` | `rt2800usb` | RT5370 y familia |
| `kernel-mt7601u` | `mt7601u` | MT7601U |
| `kernel-mt7921u` | `mt7921u` | MT7921AU |
| `kernel-rtl8xxxu` | `rtl8xxxu` | RTL8188EU/8192EU |
| `kernel-iwlwifi` | `iwlwifi` | Tarjetas Intel PCI |

Estas recetas declaran `verified: []`. Antena puede decir “driver cargado,
interfaz presente, escaneo funciona”, pero no “modelo verificado por Antena”.

## Conflictos

Antes de instalar, el helper comprueba:

- si el módulo primario ya existe y DKMS lo tiene instalado para el kernel en
  ejecución → no hace nada (idempotencia);
- si existe un módulo de otro origen → error `driver_conflict`, sin sobrescribir;
- si el paquete esperado no es el instalado pero hay paquetes `aic8800*` →
  el diagnóstico lo muestra como conflicto y no se actúa automáticamente.

No se desinstalan controladores previos. El usuario decide.

## Kernel y headers

El instalador DKMS requiere `/lib/modules/$(uname -r)/build`. Antena detecta el
paquete de headers según el flavor (`linux-headers`, `linux-lts-headers`,
`linux-zen-headers`, `linux-cachyos-headers`, `linux-hardened-headers`) y solo
instala el que corresponde al kernel en ejecución. Si el kernel cambió y no se
ha reiniciado, el diagnóstico lo indica y no se declara éxito.

## Licencias

- Código de Antena: GPL-3.0-or-later.
- Controlador AIC: GPL-2.0-only, descargado desde su repositorio; no se incluye
  en el paquete.
- Firmware: se instala desde el tarball del controlador con su licencia de
  origen; no se redistribuye en el repositorio de Antena.
- `linux-firmware`: paquete oficial de Arch.

Al añadir una receta, documenta licencia y procedencia. No se aceptan binarios
sin licencia clara ni descargas sin hash.
