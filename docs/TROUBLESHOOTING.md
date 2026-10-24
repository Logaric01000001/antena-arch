# Solución de problemas

## Primeros pasos

```bash
antena --detect
antena --diagnose
antena --scan
```

`--diagnose` no modifica nada. El botón **Exportar diagnóstico** de la GUI
genera un JSON local sin contraseñas ni SSID guardados.

## La antena no aparece

1. Prueba otro puerto USB, preferiblemente directo (sin hub).
2. Comprueba que el dispositivo está presente:

   ```bash
   lsusb
   ls /sys/bus/usb/devices
   journalctl -k -b | tail -80
   ```

3. Si aparece como `1111:1111` o como unidad de almacenamiento, está en modo
   USB inicial. Antena debe mostrar **Necesita configuración**.
4. Si no aparece en `lsusb`, el problema es físico, del cable, del puerto o del
   firmware del adaptador; Antena no puede arreglarlo.

## Necesita configuración pero falla el controlador

Comprueba el kernel y los encabezados:

```bash
uname -r
ls -l /lib/modules/$(uname -r)/build
pacman -Q linux-headers dkms
dkms status
```

Si el kernel se actualizó y no reiniciaste, el módulo DKMS puede no existir para
el kernel en ejecución. Reinicia o instala los headers correspondientes. Antena
detecta el flavor (`linux`, `lts`, `zen`, `cachyos`, `hardened`).

Con **Secure Boot** activo, el módulo DKMS debe estar firmado o debes enrolar
una clave MOK. Antena no desactiva Secure Boot ni toca el firmware. Comprueba:

```bash
mokutil --sb-state 2>/dev/null || true
journalctl -k -b | grep -i 'module verification failed\|key was rejected'
```

Si `dkms status` muestra un fallo de compilación:

```bash
sudo dkms autoinstall
```

o usa **Diagnóstico → Reconstruir el módulo** en Antena. Revisa el detalle
técnico: suele ser un header ausente o un cambio incompatible del kernel.

## Aparece `a69c:8d80` pero no hay interfaz

Es la etapa de transición. Espera unos segundos y pulsa **Actualizar**. Si no
aparece `wlanN`:

```bash
lsmod | grep -E 'aic|cfg80211'
dmesg | tail -50
rfkill list
```

Antena no declara éxito hasta que existe una interfaz y el escaneo funciona.

## `rfkill` bloquea la radio

```bash
rfkill list
sudo rfkill unblock <índice>
```

Si el bloqueo es físico (`hard blocked: yes`), revisa el interruptor del
portátil o la tecla de avión. Antena no puede desbloquear hardware.

## NetworkManager no gestiona la interfaz

```bash
nmcli device status
sudo nmcli device set wlanN managed yes
```

En Antena: **Diagnóstico → Permitir la gestión**.

## El escaneo no devuelve redes

- ¿La interfaz está conectada o gestionada?
- ¿Hay bloqueo rfkill?
- ¿El driver creó la interfaz?

```bash
iw dev
nmcli device wifi rescan ifname wlanN
nmcli -f SSID,SIGNAL,FREQ device wifi list ifname wlanN
```

Un escaneo correcto sin redes visibles no es un fallo del adaptador.

## Modo monitor / prueba pasiva

Requiere `tcpdump`, autorización y que la interfaz **no** tenga una conexión
activa. Antena crea `antena-mon`, captura Beacons y la elimina. No envía nada.
Si falla:

```bash
iw list | grep -A8 'Supported interface modes'
pacman -Q tcpdump
```

Algunos drivers anuncian `monitor` pero no lo implementan correctamente. En ese
caso Antena muestra el error y no lo anuncia como verificado.

## Desinstalar sin dañar nada

```bash
sudo pacman -Rns antena-arch
```

Se retiran las reglas de persistencia de Antena. **No** se retira el
controlador DKMS de terceros. Si Antena instaló su propio controlador y quieres
retirarlo:

```bash
printf '%s\n' '{"remove_driver": true}' | sudo /usr/lib/antena/antena-helper cleanup
```

Revisa antes `/var/lib/antena/state.json` para ver qué archivos pertenecen a
Antena. Nunca borres a mano paquetes del sistema ni firmware compartido.

## Recuperar una antena tras un fallo

1. Desconecta y vuelve a conectar el adaptador.
2. Ejecuta `antena --diagnose`.
3. Si estaba en modo almacenamiento, usa **Configurar mi antena**.
4. Si el módulo quedó cargado pero sin interfaz:

   ```bash
   sudo modprobe -r aic8800_fdrv aic_load_fw
   sudo modprobe aic8800_fdrv
   ```

5. Si el kernel cambió, reinicia.

## Recopilar información para un issue

```bash
antena --diagnose --json --report /tmp/antena-diagnostico.json
```

Adjunta el archivo si no contiene datos personales. Incluye `uname -r`,
`lsusb`, `dkms status` y el modelo del adaptador. No publiques contraseñas Wi-Fi.

## Limitaciones que no son bugs

- Un chipset sin receta no se instala.
- Un ID `1111:1111` sin producto/fabricante no se toca.
- La inyección de paquetes no está soportada.
- El paquete AUR no está publicado todavía.
- Una instalación simulada en tests no demuestra compatibilidad con tu modelo.
