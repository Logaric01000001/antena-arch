# Seguridad

## Modelo de amenaza

Antena trabaja con hardware conectado por USB y ejecuta operaciones que
modifican el sistema (paquetes, DKMS, reglas udev, rfkill, NetworkManager). Los
límites de confianza son:

1. **Interfaz**: se ejecuta como el usuario, sin privilegios. No recibe
   comandos del usuario ni del hardware.
2. **Helper**: proceso root de vida corta, invocado con `pkexec`. Solo acepta
   operaciones de una lista cerrada y un JSON validado; no ejecuta shells.
3. **Catálogo**: archivos root-owned instalados por el paquete. Define
   paquetes, módulos, mensajes de modo USB, URL y hash del controlador.
4. **Dispositivo USB**: datos no confiables (producto, fabricante, serial). Se
   usan solo como criterios de coincidencia, nunca como comandos ni rutas.

## Controles implementados

- `pkexec` + helper en `/usr/lib/antena/antena-helper`, propiedad de root.
- Sin `shell=True`; todos los comandos son listas de argumentos.
- Payload limitado a 64 KiB y validado por tipo y patrón.
- Rutas USB con regex `^\d+-\d+(\.\d+)*$`; nombres de interfaz y módulo
  restringidos.
- Lista cerrada de paquetes (`dkms`, `linux-headers`, `usb_modeswitch`,
  `linux-firmware`, `tcpdump`, etc.); no se aceptan paquetes arbitrarios.
- Revalidación del VID/PID/clase/fabricante/producto justo antes de un cambio
  de modo o de instalar persistencia.
- Descarga por HTTPS, tamaño máximo, tamaño esperado y SHA-256 fijado en el
  catálogo.
- Extracción de tar con rechazo de rutas absolutas, `..`, enlaces y dispositivos.
- Registro de cada archivo creado en `/var/lib/antena/state.json`; la limpieza
  solo borra rutas registradas y con la marca `Managed by Antena` cuando
  corresponde.
- Nunca se sobrescribe una regla udev ajena; si existe un archivo no registrado,
  la operación falla.
- No se eliminan controladores de terceros en la desinstalación. La retirada de
  un controlador instalado por Antena exige `remove_driver: true`.
- No se registran contraseñas Wi-Fi, credenciales ni SSID guardados.
- Sin telemetría ni cuentas.

## Riesgos residuales

- Un usuario con privilegios de root puede modificar el catálogo o el helper;
  eso queda fuera del modelo de amenaza.
- El controlador de terceros se compila y ejecuta en el kernel. Antena verifica
  integridad y procedencia, pero no puede garantizar la calidad del código de
  terceros.
- El cambio de modo USB y la carga de módulos afectan al dispositivo
  seleccionado; Antena comprueba la identidad, pero un error de hardware o de
  firmware puede dejar el adaptador en un estado que requiera reconectarlo.
- La prueba en modo monitor crea una interfaz temporal y captura tramas Beacon;
  no se ejecuta si la interfaz tiene una conexión activa.

## Reportar una vulnerabilidad

No uses issues públicos. Utiliza el reporte privado de vulnerabilidades de
GitHub:

https://github.com/Logaric01000001/antena-arch/security/advisories/new

Si el formulario no está disponible, contacta con `@Logaric01000001` a través
de GitHub sin publicar detalles explotables.

Incluye:

- versión de Antena y de Arch;
- descripción del impacto;
- pasos de reproducción;
- evidencia mínima (sin datos personales);
- si lo deseas, una propuesta de solución.

Objetivo de respuesta: 7 días para acusar recibo y 30 días para una evaluación
inicial. No se promete un plazo de corrección mayor del necesario.
