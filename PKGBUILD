# Maintainer: Log4ric <198108252+Logaric01000001@users.noreply.github.com>
pkgname=antena-arch
pkgver=0.1.0
pkgrel=1
pkgdesc="Asistente gráfico para configurar adaptadores Wi-Fi USB en Arch Linux"
arch=('any')
url="https://github.com/Logaric01000001/antena-arch"
license=('GPL-3.0-or-later')
depends=('python' 'python-gobject' 'gtk4' 'libadwaita' 'networkmanager' 'polkit' 'usb_modeswitch' 'dkms' 'iw' 'pacman')
optdepends=(
  'linux-headers: compilar controladores DKMS para el kernel en ejecución'
  'linux-lts-headers: encabezados para el kernel LTS'
  'linux-zen-headers: encabezados para el kernel Zen'
  'linux-cachyos-headers: encabezados para el kernel CachyOS'
  'tcpdump: prueba pasiva de recepción en modo monitor'
)
install=antena-arch.install
options=(!strip)

# Compilación local desde el repositorio clonado. El paquete listo para AUR
# está en packaging/aur/PKGBUILD, con el tarball y el hash del tag publicado.
source=()
sha256sums=()

package() {
  local src="$startdir"

  install -d "$pkgdir/usr/lib/antena"
  cp -a "$src/antena" "$pkgdir/usr/lib/antena/antena"
  find "$pkgdir/usr/lib/antena/antena" -type d -name '__pycache__' -prune -exec rm -rf {} +
  find "$pkgdir/usr/lib/antena/antena" -type f -name '*.pyc' -delete
  # El script de udev se instala una sola vez, en /usr/lib/antena/bin.
  rm -rf "$pkgdir/usr/lib/antena/antena/bin"

  install -Dm755 "$src/bin/antena" "$pkgdir/usr/bin/antena"
  install -Dm755 "$src/bin/antena-helper" "$pkgdir/usr/lib/antena/antena-helper"
  install -Dm755 "$src/antena/bin/antena-modeswitch-aic8800d80" \
    "$pkgdir/usr/lib/antena/bin/antena-modeswitch-aic8800d80"

  install -d "$pkgdir/usr/share/antena/catalog"
  install -m644 "$src"/antena/catalog/*.json "$pkgdir/usr/share/antena/catalog/"

  install -Dm644 "$src/antena/data/icons/hicolor/scalable/apps/io.github.antena.Antena.svg" \
    "$pkgdir/usr/share/icons/hicolor/scalable/apps/io.github.antena.Antena.svg"
  install -Dm644 "$src/antena/data/icons/hicolor/symbolic/apps/io.github.antena.Antena-symbolic.svg" \
    "$pkgdir/usr/share/icons/hicolor/symbolic/apps/io.github.antena.Antena-symbolic.svg"
  install -Dm644 "$src/packaging/io.github.antena.Antena.desktop" \
    "$pkgdir/usr/share/applications/io.github.antena.Antena.desktop"
  install -Dm644 "$src/packaging/io.github.antena.Antena.metainfo.xml" \
    "$pkgdir/usr/share/metainfo/io.github.antena.Antena.metainfo.xml"

  install -Dm644 "$src/LICENSE" "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
  install -Dm644 "$src/README.md" "$pkgdir/usr/share/doc/$pkgname/README.md"
  install -Dm644 "$src/CHANGELOG.md" "$pkgdir/usr/share/doc/$pkgname/CHANGELOG.md"
}
