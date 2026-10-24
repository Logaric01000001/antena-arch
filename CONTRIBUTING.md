# Contribuir a Antena

Gracias por querer mejorar Antena. Este proyecto prefiere **cobertura
verificada** antes que una lista larga de modelos.

## Antes de empezar

- Usa Arch Linux o un derivado con `base-devel`.
- No ejecutes `makepkg` como root.
- No publiques firmware ni controladores de terceros sin revisar su licencia.
- No añadas funciones ofensivas de Wi-Fi: este proyecto es de instalación,
  conectividad y diagnóstico.

## Entorno de desarrollo

```bash
git clone https://github.com/Logaric01000001/antena-arch
cd antena-arch
python -m venv .venv --system-site-packages
.venv/bin/pip install pytest
.venv/bin/pytest -q
```

Para probar la interfaz desde el repositorio:

```bash
PYTHONPATH=. python3 -m antena
```

Para el helper privilegiado en desarrollo hace falta instalarlo con el paquete;
la GUI detecta su ausencia y lo explica sin ejecutar nada.

## Estilo de código

- Python 3.11+ (probado con 3.14), sin dependencias fuera de PyGObject.
- Sin `shell=True`, sin concatenar entrada externa en comandos.
- Listas de argumentos, rutas validadas y tiempos límite.
- Funciones pequeñas y nombres explícitos; comentarios solo donde aportan.
- La lógica de detección, catálogo, diagnóstico y planificación no importa GTK.
- Los textos visibles van en `antena/i18n.py` (español e inglés).
- No se guardan secretos, contraseñas Wi-Fi ni SSID en logs.

Antes de enviar:

```bash
.venv/bin/pytest -q
python3 -m compileall -q antena
desktop-file-validate packaging/io.github.antena.Antena.desktop
appstreamcli validate packaging/io.github.antena.Antena.metainfo.xml
makepkg -f
```

## Añadir hardware

Lee [`docs/ADDING_DEVICES.md`](docs/ADDING_DEVICES.md). Una receta nueva debe
incluir:

- identificación y condiciones de coincidencia;
- evidencia de hardware real (kernel, adaptador, resultado);
- fuente, versión y licencia del controlador;
- SHA-256 si hay descarga;
- dependencias y firmware;
- comprobaciones de éxito y problemas conocidos;
- capacidades verificadas separadas de las anunciadas;
- pruebas para los estados de error.

Las recetas que solo detectan un controlador del kernel deben declararlo
explícitamente y no presentarse como verificadas.

## Pull requests

- Un cambio por PR, con una descripción clara del problema y la solución.
- Incluye pruebas nuevas o actualiza las existentes.
- Indica qué se probó en hardware real y qué solo en simulación.
- No incluyas capturas con datos personales, SSID reales o direcciones MAC.
- No cambies la versión ni el changelog salvo que el mantenedor lo pida.

## Reportes de seguridad

No abras un issue público para vulnerabilidades. Sigue [`SECURITY.md`](SECURITY.md).
