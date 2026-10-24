# Changelog

Todas las fechas usan UTC.

## [0.1.0] — 2026-10-24

Primera versión.

### Añadido

- Detección universal en modo lectura de adaptadores USB e internos mediante
  sysfs, udev, NetworkManager, iw, rfkill, modinfo, DKMS y pacman.
- Modelo de estados separado: USB, chipset, controlador instalado, controlador
  cargado, interfaz, escaneo y conectividad.
- Receta verificada **AIC8800D80** con:
  - etapas USB `1111:1111` → `a69c:8d80` → `a69c:8d83`;
  - controlador DKMS 6.4.3.0 desde una fuente fijada por SHA-256;
  - cambio de modo USB con los mensajes verificados;
  - persistencia udev específica por VID/PID, fabricante y producto;
  - capacidades verificadas y no verificadas separadas.
- Catálogo extensible con validación de esquema y recetas para controladores
  nativos (`ath9k_htc`, `rt2800usb`, `mt7601u`, `mt7921u`, `rtl8xxxu`,
  `iwlwifi`).
- Motor de diagnóstico con acciones concretas para rfkill, NetworkManager,
  encabezados, DKMS, firmware, conflictos y modo de almacenamiento.
- Planificador y ejecutor con verificación real después de cada etapa,
  cancelación y detección de desconexiones.
- Helper privilegiado con lista cerrada de operaciones, validación de payload,
  revalidación del dispositivo, descarga HTTPS con hash y extracción segura.
- Interfaz GTK4/libadwaita con Inicio, Mi antena, Diagnóstico, Ajustes y Acerca
  de; español e inglés; modo claro y oscuro; detalles técnicos opcionales.
- Prueba de escaneo real con NetworkManager y prueba pasiva de Beacons en modo
  monitor (opcional, requiere tcpdump).
- Empaquetado Arch: `PKGBUILD`, `.desktop`, iconos propios, metadatos AppStream,
  `install.sh` y limpieza de desinstalación que no toca controladores ajenos.
- Paquete AUR reproducible en `packaging/aur/` (`PKGBUILD`, `.SRCINFO`,
  `.install`) construido desde el tarball del tag; pendiente de subida a AUR.
- Suite de pruebas con sysfs simulado y runner falso (20 escenarios de diseño).

### Limitaciones conocidas

- La instalación DKMS real no se ejecutó en el equipo de pruebas porque el
  controlador ya estaba instalado; la ruta está probada con simulaciones.
- El cambio de modo USB y la persistencia no se aplicaron de nuevo sobre el
  adaptador operativo durante esta versión.
- La prueba de modo monitor no se ejecutó con privilegios en esta sesión.
- La inyección de paquetes no está verificada ni soportada.
- El paquete AUR no se ha publicado.
