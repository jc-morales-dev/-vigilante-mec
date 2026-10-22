"""Comprueba que todo lo que importan codigo/app.py y codigo/motor.py viene dentro del lanzador construido.

El código se actualiza solo, pero solo puede usar los módulos que trae la app instalada: si usa uno
que no está, la ventana no abre. publicar lo ejecuta antes de subir nada.

    python herramientas/comprobar_modulos.py [ruta/al/VigilanteMEC.exe]
"""
import ast
import sys
import zipfile
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

RAIZ = Path(__file__).resolve().parent.parent
EXE = RAIZ / "build" / "dist" / "VigilanteMEC" / "VigilanteMEC.exe"
PROPIOS = {"app", "motor"}


def modulos_del_lanzador(exe):
    car = CArchiveReader(str(exe))
    pyz = next(n for n in car.toc if n.endswith(".pyz"))
    mods = set(car.open_embedded_archive(pyz).toc)
    base = exe.parent / "_internal" / "base_library.zip"
    if base.exists():
        with zipfile.ZipFile(base) as z:
            for n in z.namelist():
                if n.endswith(".pyc"):
                    mods.add(n[:-4].replace("/", ".").removesuffix(".__init__"))
    # Módulos de C (.pyd / .so) que van como archivos sueltos.
    for f in (exe.parent / "_internal").glob("*.pyd"):
        mods.add(f.name.split(".")[0])
    mods |= set(sys.builtin_module_names)
    return mods


def importados(archivo):
    nombres = set()
    for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
        if isinstance(nodo, ast.Import):
            nombres |= {a.name for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom) and nodo.module and not nodo.level:
            nombres.add(nodo.module)
            # "from tkinter import font" importa el submódulo tkinter.font
            nombres |= {f"{nodo.module}.{a.name}" for a in nodo.names}
    return nombres


def comprobar(exe=EXE):
    if not Path(exe).exists():
        print(f"(No encuentro {exe}: construye el instalador para poder comprobar los módulos.)")
        return True
    disponibles = modulos_del_lanzador(Path(exe))
    faltan = []
    for archivo in (RAIZ / "codigo" / "app.py", RAIZ / "codigo" / "motor.py"):
        for nombre in sorted(importados(archivo)):
            raiz_mod = nombre.split(".")[0]
            if raiz_mod in PROPIOS:
                continue
            es_modulo = nombre in disponibles or any(m.startswith(nombre + ".") for m in disponibles)
            padre = nombre.rsplit(".", 1)[0]
            # "from x import algo" donde algo es una función/clase (no un módulo): basta con que exista x.
            if not es_modulo and "." in nombre and padre in disponibles and not nombre.startswith("tkinter."):
                continue
            if not es_modulo:
                faltan.append(f"{archivo.name}: {nombre}")
    if faltan:
        print("FALTAN en la app instalada (no publiques así):\n  " + "\n  ".join(faltan))
        return False
    print("Módulos OK: todo lo que usa el código viene en la app instalada.")
    return True


if __name__ == "__main__":
    sys.exit(0 if comprobar(*(sys.argv[1:2] or [EXE])) else 1)
