"""Genera los instaladores de Linux para José, con su config dentro. Llevan el token del bot:
mándaselos por privado, nunca los subas al servidor.

  privado/Vigilante-MEC-Jose.tar.gz       instalador con ventana (doble clic, sin comandos)
  privado/instalar_vigilante_jose.sh      alternativa por terminal:  bash instalar_vigilante_jose.sh
"""
import base64
import io
import json
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REPO = "jc-morales-dev/-vigilante-mec"
BASE_RELEASE = f"https://github.com/{REPO}/releases/download/lanzador-v1"
URL_LINUX = f"{BASE_RELEASE}/vigilante-mec-linux-x86_64.tar.gz"
URL_INSTALADOR = f"{BASE_RELEASE}/instalar-vigilante-mec-linux-x86_64"
CONFIG = RAIZ / "privado" / "config_jose.json"
SALIDA = RAIZ / "privado" / "instalar_vigilante_jose.sh"
PAQUETE = RAIZ / "privado" / "Vigilante-MEC-Jose.tar.gz"
LEEME = """VIGILANTE MEC - cómo instalarlo

1. Haz doble clic en "Instalar Vigilante MEC".
   (Si no se abre: clic derecho > Propiedades > Permisos > marca "Permitir ejecutar
   el archivo como un programa", o clic derecho > "Ejecutar como un programa".)
2. Lee el aviso, marca "Lo entiendo y acepto" y pulsa Instalar.
3. Espera a que termine (si no tienes Chrome, lo baja solo).
4. La primera vez, inicia sesión en el MEC en la ventana de Chrome que se abre
   y abre tu trámite hasta el paso Agenda. Desde ahí sigue sola.

Después la encuentras como "Vigilante MEC" en el escritorio y en el menú de aplicaciones.
No compartas estos archivos: llevan datos privados.
"""

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


def agregar(tar, nombre, datos, modo):
    info = tarfile.TarInfo(nombre)
    info.size = len(datos)
    info.mode = modo
    info.mtime = int(time.time())
    tar.addfile(info, io.BytesIO(datos))


def main(config=CONFIG, salida=SALIDA, paquete=PAQUETE):
    cfg = json.loads(Path(config).read_text(encoding="utf-8"))
    datos = base64.b64encode(json.dumps(cfg, ensure_ascii=False).encode("utf-8")).decode("ascii")

    texto = PLANTILLA.replace("__URL__", URL_LINUX).replace("__CONFIG__", datos)
    Path(salida).parent.mkdir(parents=True, exist_ok=True)
    Path(salida).write_bytes(texto.encode("utf-8"))  # saltos de línea de Linux
    print(f"Listo: {salida}")

    if paquete:
        with urllib.request.urlopen(URL_INSTALADOR, timeout=120) as r:
            instalador = r.read()
        with tarfile.open(paquete, "w:gz") as tar:
            carpeta = tarfile.TarInfo("Vigilante MEC")
            carpeta.type, carpeta.mode, carpeta.mtime = tarfile.DIRTYPE, 0o755, int(time.time())
            tar.addfile(carpeta)
            agregar(tar, "Vigilante MEC/Instalar Vigilante MEC", instalador, 0o755)
            agregar(tar, "Vigilante MEC/config.vmec", datos.encode("ascii"), 0o600)
            agregar(tar, "Vigilante MEC/LEEME.txt", LEEME.encode("utf-8"), 0o644)
        print(f"Listo: {paquete}")
    print("Mándaselo a José por privado.")


if __name__ == "__main__":
    # Opcional: config y salida propias (lo usa la prueba automática con una config falsa).
    if len(sys.argv) > 1:
        main(sys.argv[1], sys.argv[2], None)
    else:
        main()
