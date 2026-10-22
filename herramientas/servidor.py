"""Herramientas del administrador para el servidor de Vigilante MEC (este repositorio en GitHub).

    python herramientas/servidor.py publicar [versión]   empaqueta codigo/ y lo publica (las apps se actualizan solas)
    python herramientas/servidor.py eliminar [mensaje]   desactiva la app: se quita sola de todos los equipos
    python herramientas/servidor.py reactivar            vuelve a permitir la app (para instalar de nuevo)
    python herramientas/servidor.py estado               muestra el manifest publicado
"""
import hashlib
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REPO = "Victor00128/vigilante-mec"
MANIFEST = RAIZ / "manifest.json"
CODIGO = RAIZ / "codigo"
PAQUETES = RAIZ / "paquetes"
ARCHIVOS_CODIGO = ("app.py", "motor.py", "icono.png", "VERSION")


def leer():
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"activo": True, "version_codigo": "0.0.0", "lanzador_minimo": 1, "mensaje": "", "ajustes": {}}


def escribir(man):
    man["actualizado"] = time.strftime("%Y-%m-%d %H:%M:%S")
    MANIFEST.write_text(json.dumps(man, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def git(*args):
    subprocess.run(["git", *args], cwd=RAIZ, check=True)


def subir(mensaje):
    git("add", "-A")
    hay_cambios = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=RAIZ).returncode != 0
    if hay_cambios:
        git("commit", "-m", mensaje)
    git("push", "-u", "origin", "main")


def siguiente(version):
    partes = [int(x) for x in version.split(".")] + [0, 0, 0]
    return f"{partes[0]}.{partes[1]}.{partes[2] + 1}"


def publicar(version=None):
    man = leer()
    version = version or siguiente(man.get("version_codigo", "0.0.0"))
    for nombre in ("app.py", "motor.py"):
        compile((CODIGO / nombre).read_text(encoding="utf-8"), nombre, "exec")  # no publicar código roto
    (CODIGO / "VERSION").write_text(version + "\n", encoding="utf-8")
    PAQUETES.mkdir(exist_ok=True)
    paquete = PAQUETES / f"codigo-{version}.zip"
    with zipfile.ZipFile(paquete, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre in ARCHIVOS_CODIGO:
            z.write(CODIGO / nombre, nombre)
    man.update(version_codigo=version, sha256=hashlib.sha256(paquete.read_bytes()).hexdigest(),
               codigo_url=f"https://raw.githubusercontent.com/{REPO}/main/paquetes/{paquete.name}", activo=True)
    man.pop("mensaje", None)
    escribir(man)
    subir(f"Publicar código {version}")
    print(f"\nPublicada la versión {version}. Las apps la bajan al abrirse o en menos de 1 hora.")


def eliminar(mensaje):
    print("ATENCIÓN: esto quita Vigilante MEC (y sus datos) de TODOS los equipos donde esté instalada.")
    if input("Escribe ELIMINAR para confirmar: ").strip().upper() != "ELIMINAR":
        print("Cancelado.")
        return
    man = leer()
    man.update(activo=False, mensaje=mensaje or "El administrador desactivó Vigilante MEC.")
    escribir(man)
    subir("Desactivar la app en todos los equipos")
    print("\nApp DESACTIVADA. Cada equipo la quitará (con sus datos) al abrirse o en menos de 1 hora.")
    print("Para volver a instalarla más adelante, primero: reactivar")


def reactivar():
    man = leer()
    man.update(activo=True)
    man.pop("mensaje", None)
    escribir(man)
    subir("Reactivar la app")
    print("\nApp reactivada: ya se puede instalar de nuevo.")


if __name__ == "__main__":
    orden = sys.argv[1] if len(sys.argv) > 1 else "estado"
    resto = " ".join(sys.argv[2:])
    if orden == "publicar":
        publicar(resto or None)
    elif orden == "eliminar":
        eliminar(resto)
    elif orden == "reactivar":
        reactivar()
    else:
        print(json.dumps(leer(), indent=2, ensure_ascii=False))
