# Empaquetado

## Estado actual

Antena tiene tres formatos de instalación:

| Formato | Ruta | Estado |
|---|---|---|
| Build local desde el repositorio | `PKGBUILD` | Verificado con `makepkg` |
| Paquete binario `any` | release `v0.1.1` | Publicado, sin firma |
| Paquete AUR | `packaging/aur/` | **Preparado y probado; pendiente de subir a AUR** |

El paquete AUR **no está publicado**. `yay -S antena-arch` no funcionará hasta
que se suba con una cuenta de AUR. No se debe afirmar lo contrario.

## Build local

```bash
cd antena-arch
makepkg -f
sudo pacman -U antena-arch-0.1.1-1-any.pkg.tar.zst
```

`install.sh` automatiza lo mismo sin ejecutar `makepkg` como root.

## Paquete AUR

El directorio `packaging/aur/` contiene exactamente lo que debe ir al
repositorio AUR:

```
PKGBUILD
.SRCINFO
antena-arch.install
```

El `PKGBUILD` usa el tarball inmutable del tag publicado:

```
https://github.com/Logaric01000001/antena-arch/archive/refs/tags/v0.1.1.tar.gz
```

SHA-256:

```
05e29b8da521a5515ec7d9527ad7690c2d1f2420b811f565950af346b7f7c8fb
```

Build reproducible comprobado desde un directorio limpio:

```bash
cp packaging/aur/{PKGBUILD,.SRCINFO,antena-arch.install} /tmp/aur-antena/
cd /tmp/aur-antena
makepkg -f
```

El paquete resultante se puede inspeccionar con:

```bash
pacman -Qip antena-arch-0.1.1-1-any.pkg.tar.zst
bsdtar -tf antena-arch-0.1.1-1-any.pkg.tar.zst
```

## Publicar en AUR

Requisitos: cuenta de AUR y una clave SSH registrada en
https://aur.archlinux.org/account/.

```bash
# 1. Clave propia de AUR (si no existe)
ssh-keygen -t ed25519 -C "aur-antena" -f ~/.ssh/aur

# 2. Añade ~/.ssh/aur.pub en la cuenta de AUR

# 3. Clona el repositorio AUR del paquete nuevo
git clone ssh://aur@aur.archlinux.org/antena-arch.git ~/aur-antena

# 4. Copia los archivos preparados
cp packaging/aur/PKGBUILD \
   packaging/aur/.SRCINFO \
   packaging/aur/antena-arch.install ~/aur-antena/

# 5. Publica
cd ~/aur-antena
git add PKGBUILD .SRCINFO antena-arch.install
git commit -m "Initial upload: antena-arch 0.1.1-1"
git push
```

Después de la subida, el paquete aparecerá en
https://aur.archlinux.org/packages/antena-arch y `yay -S antena-arch` debería
funcionar. Hasta entonces, el comando anterior no es válido.

## Actualizar el paquete

1. Cambia `pkgver` en `packaging/aur/PKGBUILD` (y `pkgrel=1`).
2. Crea y publica el tag `vX.Y.Z` en GitHub.
3. Descarga el tarball del tag y calcula `sha256sum`.
4. Sustituye el hash en `PKGBUILD`.
5. Regenera `.SRCINFO`:

   ```bash
   cd packaging/aur
   makepkg --printsrcinfo > .SRCINFO
   ```

6. Construye desde cero en un directorio limpio.
7. Haz commit y push al repositorio AUR.

Nunca uses `sha256sums=('SKIP')` en un paquete publicado.

## Seguridad del paquete

- El paquete no incluye firmware ni controladores de terceros.
- El helper se instala root-owned y se invoca con `pkexec`.
- Los archivos persistentes se crean en tiempo de ejecución y se registran en
  `/var/lib/antena/state.json`.
- `pre_remove` retira solo la persistencia de Antena; no desinstala
  controladores DKMS ajenos.
- El paquete binario de la release no está firmado. Verifica el SHA-256 o
  construye localmente.
