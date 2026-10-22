"""Instalador de Vigilante MEC para Linux con ventana (sin comandos).

Es genérico (se construye en GitHub Actions); los datos de cada persona (token, chats, rol) van en
el archivo config.vmec que se pone al lado. Instala por usuario, sin permisos de administrador:
~/.local/share/vigilante-mec (app y datos) y sus accesos directos.

    "Instalar Vigilante MEC"                       ventana normal
    "Instalar Vigilante MEC" --sin-ventana --acepto   lo mismo por consola (pruebas automáticas)
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.request
from pathlib import Path

APP = "Vigilante MEC"
REPO = "jc-morales-dev/-vigilante-mec"
URL_APP = f"https://github.com/{REPO}/releases/download/lanzador-v1/vigilante-mec-linux-x86_64.tar.gz"
DATOS = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "vigilante-mec"
APPDIR = DATOS / "app"
EXE = APPDIR / "vigilante-mec"
AVISO = ("Vigila los cupos de la Agenda del MEC y avisa por Telegram.\n\n"
         "Importante: la app se actualiza sola desde el servidor del administrador "
         f"(GitHub {REPO}). El administrador también puede desactivarla a distancia: en ese caso "
         "se quita sola de este equipo junto con sus datos. Solo usa sus propias carpetas "
         "(~/.local/share/vigilante-mec) y sus accesos directos.")


def carpeta_propia():
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


def leer_config():
    for nombre in ("config.vmec", "config.json"):
        ruta = carpeta_propia() / nombre
        if ruta.exists():
            texto = ruta.read_text(encoding="utf-8").strip()
            try:
                return json.loads(texto)
            except ValueError:
                return json.loads(base64.b64decode(texto).decode("utf-8"))
    raise RuntimeError("Falta el archivo config.vmec al lado del instalador. Pídeselo a quien te lo mandó.")


def escritorio():
    try:
        r = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5)
        if r.stdout.strip():
            return Path(r.stdout.strip())
    except Exception:
        pass
    return Path.home() / "Desktop"


def entrada(extra=""):
    return "\n".join(["[Desktop Entry]", "Type=Application", f"Name={APP}",
                      "Comment=Vigila los cupos de la Agenda del MEC", f'Exec="{EXE}"{extra}',
                      f"Icon={APPDIR / '_internal' / 'icono.png'}", "Terminal=false", "Categories=Utility;", ""])


def hay_chrome():
    for nombre in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        ruta = shutil.which(nombre)
        if ruta and "/snap/" not in os.path.realpath(ruta):
            return True
    return False


def navegador_ok():
    try:
        r = subprocess.run([str(EXE), "--probar-navegador"], capture_output=True, text=True, timeout=180)
        return "NAVEGADOR_OK" in r.stdout
    except Exception:
        return False


def instalar(cfg, icono_escritorio, arranque, paso, avance):
    paso("Bajando la app…")
    tmp = Path(tempfile.mkstemp(suffix=".tar.gz")[1])
    with urllib.request.urlopen(URL_APP, timeout=60) as r, tmp.open("wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        bajado = 0
        while True:
            trozo = r.read(1 << 16)
            if not trozo:
                break
            f.write(trozo)
            bajado += len(trozo)
            if total:
                avance(bajado * 50 // total)

    paso("Instalando…")
    subprocess.run(["pkill", "-f", str(APPDIR)], capture_output=True)
    DATOS.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(APPDIR, ignore_errors=True)
    APPDIR.mkdir(parents=True)
    with tarfile.open(tmp) as t:
        for m in t.getmembers():
            partes = Path(m.name).parts[1:]  # quita la carpeta "vigilante-mec/" del paquete
            if not partes:
                continue
            m.name = str(Path(*partes))
            t.extract(m, APPDIR)
    tmp.unlink()
    config = DATOS / "config_instalador.json"
    config.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    os.chmod(config, 0o600)
    avance(60)

    paso("Creando accesos directos…")
    aplicaciones = Path.home() / ".local" / "share" / "applications"
    aplicaciones.mkdir(parents=True, exist_ok=True)
    (aplicaciones / "vigilante-mec.desktop").write_text(entrada(), encoding="utf-8")
    binarios = Path.home() / ".local" / "bin"
    binarios.mkdir(parents=True, exist_ok=True)
    enlace = binarios / "vigilante-mec"
    enlace.unlink(missing_ok=True)
    enlace.symlink_to(EXE)
    if icono_escritorio and escritorio().is_dir():
        acceso = escritorio() / "vigilante-mec.desktop"
        acceso.write_text(entrada(), encoding="utf-8")
        acceso.chmod(0o755)
        subprocess.run(["gio", "set", str(acceso), "metadata::trusted", "true"], capture_output=True)
    inicio = Path.home() / ".config" / "autostart" / "vigilante-mec.desktop"
    if arranque:
        inicio.parent.mkdir(parents=True, exist_ok=True)
        inicio.write_text(entrada(" --auto") + "X-GNOME-Autostart-enabled=true\n", encoding="utf-8")
    else:
        inicio.unlink(missing_ok=True)
    avance(65)

    if not hay_chrome():
        paso("Bajando el navegador (unos 150 MB, puede tardar)…")
        subprocess.run([str(EXE), "--instalar-navegador"], capture_output=True)
    avance(85)
    paso("Comprobando el navegador…")
    if not navegador_ok():
        paso("Faltan piezas del sistema: escribe tu contraseña de Linux en la ventana que aparece…")
        subprocess.run(["pkexec", str(EXE), "--instalar-dependencias"], capture_output=True)
        if not navegador_ok():
            raise RuntimeError("El navegador no arranca. Instala Google Chrome (google.com/chrome) y abre "
                               "Vigilante MEC desde el menú de aplicaciones.")
    avance(100)
    paso("¡Listo! Abriendo Vigilante MEC…")
    subprocess.Popen([str(EXE)], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def sin_ventana():
    if "--acepto" not in sys.argv:
        print(AVISO)
        if input("\nEscribe SI para aceptar e instalar: ").strip().upper() not in ("SI", "SÍ"):
            print("Cancelado.")
            return 1
    instalar(leer_config(), True, False, lambda t: print(t, flush=True), lambda p: None)
    print("INSTALADOR_OK")
    return 0


def ventana():
    import tkinter as tk
    from tkinter import messagebox, ttk

    fondo, tarjeta, texto, tenue, verde = "#0f172a", "#1e293b", "#e2e8f0", "#94a3b8", "#22c55e"
    raiz = tk.Tk()
    raiz.title(f"Instalar {APP}")
    raiz.configure(bg=fondo)
    raiz.resizable(False, False)
    marco = tk.Frame(raiz, bg=fondo, padx=26, pady=22)
    marco.pack()
    tk.Label(marco, text=f"Instalar {APP}", bg=fondo, fg=texto, font=("Sans", 17, "bold")).pack(anchor="w")
    tk.Label(marco, text=AVISO, bg=fondo, fg=tenue, wraplength=470, justify="left").pack(anchor="w", pady=(10, 12))

    try:
        cfg = leer_config()
    except Exception as e:
        messagebox.showerror(APP, str(e))
        return 1

    def casilla(t, valor):
        var = tk.BooleanVar(value=valor)
        c = tk.Checkbutton(marco, text=t, variable=var, bg=fondo, fg=texto, selectcolor=tarjeta,
                           activebackground=fondo, activeforeground=texto, highlightthickness=0, bd=0,
                           command=lambda: boton.configure(state="normal" if v_acepto.get() else "disabled"))
        c.pack(anchor="w", pady=2)
        return var

    v_acepto = casilla("Lo entiendo y acepto", False)
    tk.Frame(marco, bg="#334155", height=1).pack(fill="x", pady=10)
    v_icono = casilla("Crear icono en el escritorio", True)
    v_arranque = casilla("Abrir la app sola al prender el equipo", True)

    estilo = ttk.Style()
    estilo.theme_use("default")
    estilo.configure("V.Horizontal.TProgressbar", troughcolor=tarjeta, background=verde, bordercolor=tarjeta,
                     lightcolor=verde, darkcolor=verde)
    barra = ttk.Progressbar(marco, style="V.Horizontal.TProgressbar", length=470, maximum=100)
    txt = tk.Label(marco, text="", bg=fondo, fg=tenue, wraplength=470, justify="left")
    boton = tk.Button(marco, text="Instalar", state="disabled", bg=verde, fg="#052e16", activebackground="#4ade80",
                      relief="flat", font=("Sans", 11, "bold"), padx=26, pady=6, command=lambda: empezar())
    boton.pack(anchor="e", pady=(16, 0))

    def en_hilo(funcion):
        return lambda *a: raiz.after(0, lambda: funcion(*a))

    def empezar():
        boton.configure(state="disabled", text="Instalando…")
        barra.pack(anchor="w", pady=(14, 4))
        txt.pack(anchor="w")

        def tarea():
            try:
                instalar(cfg, v_icono.get(), v_arranque.get(), en_hilo(lambda t: txt.configure(text=t)),
                         en_hilo(lambda p: barra.configure(value=p)))
                raiz.after(0, terminado)
            except Exception as e:
                msg = str(e)
                raiz.after(0, lambda: fallo(msg))
        threading.Thread(target=tarea, daemon=True).start()

    def terminado():
        messagebox.showinfo(APP, "Instalación terminada.\n\nLa primera vez, inicia sesión en el MEC en la ventana "
                                 "de Chrome que se abre y abre tu trámite hasta el paso Agenda.")
        raiz.destroy()

    def fallo(msg):
        messagebox.showerror(APP, f"No se pudo instalar:\n\n{msg}")
        boton.configure(state="normal", text="Reintentar")

    raiz.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(sin_ventana() if "--sin-ventana" in sys.argv else ventana())
