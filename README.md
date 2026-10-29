# Antena

**Understand your Wi-Fi adapter before changing your system.**

A GTK4/libadwaita application for Arch Linux that detects Wi-Fi hardware, explains missing components and offers guided setup. The GUI runs as your user; a separate polkit helper handles allowed privileged operations.

[Español — documentación completa](README.es.md) · [Releases](https://github.com/Logaric01000001/antena-arch/releases) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

## Screenshots

![Antena home screen, captured from the running application](docs/screenshots/home.png)

<details>
<summary>Device details, diagnostics and setup assistant</summary>

![Device details](docs/screenshots/device.png)
![Diagnostics](docs/screenshots/diagnostics.png)
![Setup assistant](docs/screenshots/repair.png)

</details>

Existing screenshots are from the running application, as documented in the Spanish README. They are not newly executed hardware tests.

## What it does

- Detects USB and internal Wi-Fi hardware using Linux system interfaces and NetworkManager.
- Separates device detection, driver availability, loaded module, interface and scan state.
- Provides diagnostics, a CLI and local technical reports.
- Isolates privileged operations behind a closed operation allowlist.
- Supports English/Spanish and light/dark interfaces.

## Hardware status

Version **0.1.1** has a recipe for **AIC8800D80 / AX900** with recorded hardware observations. Several in-kernel drivers have detection/diagnostic recipes but have not been physically tested with Antena. Unknown chipsets do not receive a guessed installation recipe.

The DKMS install and persistence paths have simulated coverage; they were not rerun on the already working development adapter. Packet injection is not supported or verified. The AUR package is prepared but **not published**. Read the complete [compatibility table](README.es.md#compatibilidad) and [known limitations](README.es.md#limitaciones-conocidas-011) before installation.

## Install on Arch Linux

Review the installer and package definition first. Run as a normal user, not root:

```bash
git clone https://github.com/Logaric01000001/antena-arch.git
cd antena-arch
./install.sh
```

The installer builds with `makepkg` and uses `sudo pacman -U` for the package. It checks dependencies and explains what is missing. See [installation details](README.es.md#instalación) for requirements, release checksums and removal behavior. Release packages are unsigned.

## CLI examples

```bash
antena --detect
antena --diagnose
antena --json --report /tmp/antena.json
antena --version
```

These are supported commands, not fabricated sample output. Network scanning can reveal nearby SSIDs; review reports before sharing them.

## Development and contribution

```bash
python -m venv .venv --system-site-packages
.venv/bin/pip install pytest
.venv/bin/pytest -q
```

The automated suite uses simulated system state and command runners. It does not replace physical hardware testing. See [architecture](docs/ARCHITECTURE.md), [driver catalog](docs/DRIVERS.md), [adding devices](docs/ADDING_DEVICES.md) and [troubleshooting](docs/TROUBLESHOOTING.md).

Contributions are welcome: reproducible diagnostics, documentation and hardware observations. Include only sanitized logs. New recipes need evidence, driver provenance and error-path tests.

## License

Project code: **GPL-3.0-or-later**. Third-party drivers are downloaded from their documented sources rather than redistributed. See [LICENSE](LICENSE) and [driver documentation](docs/DRIVERS.md).
