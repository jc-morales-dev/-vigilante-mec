"""Genera privado/instalar_vigilante_jose.sh: instalador de Linux con la config de José ya dentro.

Ese archivo lleva el token del bot: mándaselo a José por privado, nunca lo subas al servidor.
"""
import base64
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REPO = "jc-morales-dev/-vigilante-mec"
URL_LINUX = f"https://github.com/{REPO}/releases/download/lanzador-v1/vigilante-mec-linux-x86_64.tar.gz"
CONFIG = RAIZ / "privado" / "config_jose.json"
SALIDA = RAIZ / "privado" / "instalar_vigilante_jose.sh"

PLANTILLA = r'''#!/usr/bin/env bash
# Instalador de Vigilante MEC (Linux). Uso:  bash instalar_vigilante_jose.sh
set -euo pipefail

URL="__URL__"
CONFIG_B64="__CONFIG__"
DATOS="${XDG_DATA_HOME:-$HOME/.local/share}/vigilante-mec"
APPDIR="$DATOS/app"
EXE="$APPDIR/vigilante-mec"

cat <<'AVISO'

==============================================================
                 Vigilante MEC - instalación
==============================================================
Vigila los cupos de la Agenda del MEC y avisa por Telegram.

IMPORTANTE, léelo:
 - La app se actualiza sola desde el servidor de Victor
   (GitHub jc-morales-dev/-vigilante-mec).
 - Victor puede desactivarla a distancia. En ese caso se quita
   sola de este equipo junto con sus datos (incluida la sesión
   del MEC que guarda la app).
 - Solo usa sus propias carpetas: ~/.local/share/vigilante-mec
   y sus accesos directos. No toca nada más del equipo.
==============================================================

AVISO
read -r -p "¿Lo entiendes y aceptas? Escribe SI y pulsa Enter: " RESP
case "${RESP^^}" in SI|SÍ) ;; *) echo "Cancelado, no se instaló nada."; exit 1 ;; esac
read -r -p "¿Abrir la app sola al prender el equipo? [S/n]: " ARRANQUE

if [ "$(uname -m)" != "x86_64" ]; then
  echo "Este equipo no es de 64 bits (x86_64); avisa a Victor."; exit 1
fi

echo; echo "1/4  Bajando la app..."
TMP="$(mktemp)"
if command -v curl >/dev/null; then curl -fL --progress-bar "$URL" -o "$TMP"
else wget -q --show-progress -O "$TMP" "$URL"; fi

echo "2/4  Instalando..."
pgrep -f "$APPDIR" >/dev/null 2>&1 && pkill -f "$APPDIR" || true
mkdir -p "$DATOS"
rm -rf "$APPDIR"; mkdir -p "$APPDIR"
tar -xzf "$TMP" -C "$APPDIR" --strip-components=1
rm -f "$TMP"
echo "$CONFIG_B64" | base64 -d > "$DATOS/config_instalador.json"
chmod 600 "$DATOS/config_instalador.json"

entrada() {  # $1 = argumentos extra para Exec
  printf '%s\n' "[Desktop Entry]" "Type=Application" "Name=Vigilante MEC" \
    "Comment=Vigila los cupos de la Agenda del MEC" "Exec=\"$EXE\"$1" \
    "Icon=$APPDIR/_internal/icono.png" "Terminal=false" "Categories=Utility;"
}
mkdir -p "$HOME/.local/share/applications" "$HOME/.local/bin"
entrada "" > "$HOME/.local/share/applications/vigilante-mec.desktop"
ln -sf "$EXE" "$HOME/.local/bin/vigilante-mec"
ESCRITORIO="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$ESCRITORIO" ]; then
  entrada "" > "$ESCRITORIO/vigilante-mec.desktop"
  chmod +x "$ESCRITORIO/vigilante-mec.desktop"
  gio set "$ESCRITORIO/vigilante-mec.desktop" metadata::trusted true 2>/dev/null || true
fi
case "${ARRANQUE^^}" in
  N|NO) rm -f "$HOME/.config/autostart/vigilante-mec.desktop" ;;
  *) mkdir -p "$HOME/.config/autostart"
     { entrada " --auto"; echo "X-GNOME-Autostart-enabled=true"; } > "$HOME/.config/autostart/vigilante-mec.desktop" ;;
esac

echo "3/4  Comprobando el navegador..."
HAY_CHROME=""
for n in google-chrome google-chrome-stable chromium chromium-browser; do
  r="$(command -v "$n" 2>/dev/null || true)"
  if [ -n "$r" ] && ! readlink -f "$r" | grep -q /snap/; then HAY_CHROME="$r"; break; fi
done
if [ -z "$HAY_CHROME" ]; then
  echo "     No hay Chrome: bajo Chromium para la app (unos 150 MB)..."
  "$EXE" --instalar-navegador
fi
if ! "$EXE" --probar-navegador 2>/dev/null | grep -q NAVEGADOR_OK; then
  echo "     Al navegador le faltan piezas del sistema. Te pedirá TU contraseña de Linux para instalarlas:"
  sudo "$EXE" --instalar-dependencias || true
  "$EXE" --probar-navegador 2>/dev/null | grep -q NAVEGADOR_OK || {
    echo "     El navegador sigue sin arrancar: instala Google Chrome (google.com/chrome) y abre la app."; }
fi

echo "4/4  Abriendo Vigilante MEC..."
nohup "$EXE" >/dev/null 2>&1 &
echo
echo "Listo. La app está en el menú de aplicaciones y en el escritorio (\"Vigilante MEC\")."
echo "La primera vez inicia sesión en el MEC en la ventana de Chrome que se abre."
'''


def main(config=CONFIG, salida=SALIDA):
    cfg = json.loads(Path(config).read_text(encoding="utf-8"))
    datos = base64.b64encode(json.dumps(cfg, ensure_ascii=False).encode("utf-8")).decode("ascii")
    texto = PLANTILLA.replace("__URL__", URL_LINUX).replace("__CONFIG__", datos)
    Path(salida).parent.mkdir(parents=True, exist_ok=True)
    Path(salida).write_bytes(texto.encode("utf-8"))  # saltos de línea de Linux
    print(f"Listo: {salida}\nMándaselo a José por privado. Él lo ejecuta con:  bash instalar_vigilante_jose.sh")


if __name__ == "__main__":
    # Opcional: config y salida propias (lo usa la prueba automática con una config falsa).
    main(*sys.argv[1:3])
