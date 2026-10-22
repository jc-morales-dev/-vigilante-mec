"""Construye privado/VigilanteMEC-Setup-<persona>.exe (instalador de Windows con su config dentro).

    python herramientas/construir_windows.py victor
"""
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONSTRUIR = RAIZ / "build"
# Módulos extra para que las actualizaciones del código puedan usarlos sin reinstalar
# (la misma lista está en .github/workflows/linux.yml).
EXTRA = ["--collect-submodules", "tkinter", "--collect-submodules", "email", "--collect-submodules", "http",
         "--collect-submodules", "urllib", "--collect-submodules", "json", "--collect-submodules", "html",
         "--collect-submodules", "xml", "--collect-submodules", "concurrent"]
for m in ("csv", "uuid", "zoneinfo", "statistics", "dataclasses", "base64", "hashlib", "secrets", "shlex",
          "textwrap", "difflib", "calendar", "locale", "platform", "webbrowser", "queue", "socket", "ssl"):
    EXTRA += ["--hidden-import", m]


def pyinstaller(*args):
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--workpath", str(CONSTRUIR / "work"), "--specpath", str(CONSTRUIR), *args], check=True)


def main(persona):
    config = RAIZ / "privado" / f"config_{persona}.json"
    json.loads(config.read_text(encoding="utf-8"))  # que sea JSON válido
    subprocess.run([sys.executable, str(RAIZ / "lanzador" / "hacer_icono.py")], check=True)
    icono_ico = RAIZ / "lanzador" / "icono.ico"
    icono_png = RAIZ / "codigo" / "icono.png"

    pyinstaller("--windowed", "--name", "VigilanteMEC", "--icon", str(icono_ico),
                "--distpath", str(CONSTRUIR / "dist"),
                "--add-data", f"{RAIZ / 'codigo'};codigo", "--add-data", f"{icono_png};.",
                "--paths", str(RAIZ / "codigo"), "--hidden-import", "app", "--hidden-import", "motor",
                *EXTRA, str(RAIZ / "lanzador" / "lanzador.py"))

    app_zip = CONSTRUIR / "app.zip"
    origen = CONSTRUIR / "dist" / "VigilanteMEC"
    with zipfile.ZipFile(app_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for f in origen.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(origen))

    datos_cfg = CONSTRUIR / "config_instalador.json"
    shutil.copy(config, datos_cfg)
    pyinstaller("--onefile", "--windowed", "--name", f"VigilanteMEC-Setup-{persona.capitalize()}",
                "--icon", str(icono_ico), "--distpath", str(RAIZ / "privado"),
                "--add-data", f"{app_zip};.", "--add-data", f"{icono_png};.", "--add-data", f"{datos_cfg};.",
                str(RAIZ / "lanzador" / "instalador_windows.py"))
    datos_cfg.unlink()
    print(f"\nListo: {RAIZ / 'privado' / f'VigilanteMEC-Setup-{persona.capitalize()}.exe'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "victor")
