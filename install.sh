#!/usr/bin/env bash
# Instalador local de Antena para Arch Linux.
# Construye como usuario normal y deja que pacman pida autorización.
set -euo pipefail

say() { printf '%s\n' "$*"; }
fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }

[ "$EUID" -ne 0 ] || fail "No ejecutes install.sh como root. makepkg nunca debe ejecutarse como root."
[ -f PKGBUILD ] || fail "Ejecuta este script desde la raíz del repositorio."
command -v makepkg >/dev/null 2>&1 || fail "Falta makepkg. Instala base-devel: sudo pacman -S --needed base-devel"
command -v pacman >/dev/null 2>&1 || fail "Este instalador requiere Arch Linux o una distribución basada en Arch."

if ! pacman -Qg base-devel >/dev/null 2>&1; then
  say "Falta el grupo base-devel."
  say "Instálalo con:  sudo pacman -S --needed base-devel"
  exit 1
fi

missing=()
for dep in python python-gobject gtk4 libadwaita networkmanager polkit usb_modeswitch dkms iw; do
  pacman -Q "$dep" >/dev/null 2>&1 || missing+=("$dep")
done
if [ "${#missing[@]}" -gt 0 ]; then
  say "Faltan dependencias: ${missing[*]}"
  say "Instálalas con:  sudo pacman -S --needed ${missing[*]}"
  exit 1
fi

say "Construyendo el paquete como ${USER}…"
makepkg -f --noconfirm

pkgfile=$(find . -maxdepth 1 -name "${pkgname:-antena-arch}-[0-9]*.pkg.tar.zst" -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)
[ -n "$pkgfile" ] || pkgfile=$(ls -t antena-arch-*.pkg.tar.zst 2>/dev/null | head -1)
[ -n "$pkgfile" ] || fail "No se generó el paquete."

say "Instalando $pkgfile con pacman (pedirá autorización)…"
sudo pacman -U --noconfirm "$pkgfile"

say "Listo. Abre Antena desde el menú de aplicaciones o ejecuta: antena"
