"""Herramientas del administrador para el servidor de Vigilante MEC (este repositorio en GitHub).

    python herramientas/servidor.py publicar [versión]   empaqueta codigo/ y lo publica (las apps se actualizan solas)
    python herramientas/servidor.py eliminar [mensaje]   desactiva la app: se quita sola de todos los equipos
    python herramientas/servidor.py reactivar            vuelve a permitir la app (para instalar de nuevo)
    python herramientas/servidor.py estado               muestra el manifest publicado
    python herramientas/servidor.py equipos              qué equipos están vigilando ahora (señal de vida del bot)
    python herramientas/servidor.py avisa <quién>        quién manda los avisos de cupos: Victor, Jose, todos o auto
    python herramientas/servidor.py ajuste <equipo|todos> <clave> [valor]   cambia un ajuste (sin valor lo quita)
"""
import hashlib
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REPO = "jc-morales-dev/-vigilante-mec"
MANIFEST = RAIZ / "manifest.json"
CODIGO = RAIZ / "codigo"
PAQUETES = RAIZ / "paquetes"
ARCHIVOS_CODIGO = ("app.py", "motor.py", "icono.png", "VERSION")
IDIOMAS_LATIDO = {"principal": "zu", "respaldo": "xh"}  # los mismos que codigo/motor.py
LATIDO_MAX = 150


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
    # Ni código que use módulos que la app instalada no trae (la ventana no abriría).
    sys.path.insert(0, str(RAIZ / "herramientas"))
    import comprobar_modulos
    exe = comprobar_modulos.EXE
    if not exe.exists():
        exe = Path.home() / "AppData" / "Local" / "Programs" / "VigilanteMEC" / "VigilanteMEC.exe"
    if not comprobar_modulos.comprobar(exe):
        sys.exit("No se publicó nada.")
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


def token_bot():
    for config in sorted((RAIZ / "privado").glob("config_*.json")):
        token = json.loads(config.read_text(encoding="utf-8")).get("telegram_token")
        if token:
            return token
    sys.exit("No encontré el token del bot en privado/config_*.json.")


def hace(segundos):
    if segundos < 120:
        return f"hace {segundos} s"
    if segundos < 7200:
        return f"hace {segundos // 60} min"
    return f"hace {segundos // 3600} h"


def equipos():
    token = token_bot()
    avisa = str(leer().get("ajustes", {}).get("avisa") or "auto")
    print(f"Quién avisa de los cupos: {avisa}\n")
    for rol, idioma in IDIOMAS_LATIDO.items():
        url = f"https://api.telegram.org/bot{token}/getMyShortDescription?" + urllib.parse.urlencode(
            {"language_code": idioma})
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                texto = json.loads(r.read().decode()).get("result", {}).get("short_description", "")
        except Exception as e:
            print(f"  {rol:10} no pude leer su señal: {str(e).splitlines()[0][:100]}")
            continue
        p = texto.split()
        if len(p) < 2 or not p[1].isdigit():
            print(f"  {rol:10} sin señal todavía (nunca abrió la versión nueva)")
            continue
        estado = "vigilando" if p[0] == "vivo" else p[0]
        nombre = p[2] if len(p) > 2 else "?"
        version = f"v{p[4]}" if len(p) > 4 else "versión antigua"
        segundos = int(time.time()) - int(p[1])
        if segundos > LATIDO_MAX:
            resumen = f"APAGADO o sin internet (última señal {hace(segundos)}, estaba {estado})"
        else:
            resumen = {"vigilando": "VIGILANDO", "esperando": "ESPERANDO que inicien sesión en el MEC",
                       "mudo": "encendido, con Telegram desactivado"}.get(estado, estado)
            resumen += f" ({hace(segundos)})"
        print(f"  {nombre:10} {rol:10} {version:16} {resumen}")


def valor_ajuste(texto):
    try:
        return json.loads(texto)  # números, true/false, listas...
    except ValueError:
        return texto


def cambiar_ajuste(equipo, clave, valor=None):
    """equipo 'todos' -> manifest["ajustes"]; otro nombre -> manifest["equipos"][nombre]."""
    man = leer()
    if equipo.lower() == "todos":
        destino = man.setdefault("ajustes", {})
    else:
        todos = man.setdefault("equipos", {})
        equipo = next((k for k in todos if k.lower() == equipo.lower()), equipo)
        destino = todos.setdefault(equipo, {})
    if valor is None:
        destino.pop(clave, None)
    else:
        destino[clave] = valor_ajuste(valor)
    man["equipos"] = {k: v for k, v in man.get("equipos", {}).items() if v}
    escribir(man)
    texto = f"{clave} = {destino[clave]!r}" if clave in destino else f"{clave} quitado"
    subir(f"Ajuste ({equipo}): {texto}")
    print(f"\nListo ({equipo}): {texto}. Los equipos lo aplican en menos de 5 minutos.")


def elegir_avisa(quien):
    if not quien:
        sys.exit("Indica quién avisa: Victor, Jose, todos o auto (el principal).")
    if quien.lower() == "auto":
        cambiar_ajuste("todos", "avisa")
    else:
        cambiar_ajuste("todos", "avisa", json.dumps(quien))


if __name__ == "__main__":
    orden = sys.argv[1] if len(sys.argv) > 1 else "estado"
    resto = " ".join(sys.argv[2:])
    if orden == "publicar":
        publicar(resto or None)
    elif orden == "eliminar":
        eliminar(resto)
    elif orden == "reactivar":
        reactivar()
    elif orden == "equipos":
        equipos()
    elif orden == "avisa":
        elegir_avisa(resto.strip())
    elif orden == "ajuste" and len(sys.argv) >= 4:
        cambiar_ajuste(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:]) or None)
    else:
        print(json.dumps(leer(), indent=2, ensure_ascii=False))
