"""
Vigilante MEC - lanzador (la parte fija de la app instalada).

Al abrirse revisa el servidor (manifest.json en GitHub):
  - si hay código nuevo lo baja, comprueba su sha256 y lo usa;
  - si el administrador desactivó la app, la quita de este equipo con sus datos.
Después carga la ventana (codigo/app.py) o el vigilante (codigo/motor.py) desde
la última versión bajada, o desde la copia que trae la instalación.

Uso:
    VigilanteMEC                         abre la ventana
    VigilanteMEC --auto                  abre la ventana y enciende el vigilante
    VigilanteMEC --motor                 (interno) el vigilante en sí
    VigilanteMEC --desinstalar           quitar la app de este equipo
    VigilanteMEC --instalar-navegador    bajar Chromium (si no hay Chrome)
    VigilanteMEC --probar-navegador      comprobar que el navegador arranca
"""
import hashlib
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

APP = "Vigilante MEC"
LANZADOR_VERSION = 1
REPO = "jc-morales-dev/-vigilante-mec"
MANIFEST_URL = f"https://raw.githubusercontent.com/{REPO}/main/manifest.json"

ES_WINDOWS = os.name == "nt"
CONGELADA = getattr(sys, "frozen", False)
RECURSOS = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
if ES_WINDOWS:
    DATOS = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "VigilanteMEC"
    INSTALACION = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / "VigilanteMEC"
else:
    DATOS = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "vigilante-mec"
    INSTALACION = DATOS / "app"
CODIGO = DATOS / "codigo"
CONFIG = DATOS / "config.json"
SIN_VENTANA = 0x08000000 if ES_WINDOWS else 0  # CREATE_NO_WINDOW
PUERTO_UNICO = 47653  # evita abrir dos veces la app (dos vigilantes pelearían por el mismo Chrome)

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(DATOS / "navegadores")
os.environ["VIGILANTE_DATA"] = str(DATOS)


# ---------------------------------------------------------------- Código actualizable

def version_tupla(v):
    return tuple(int(x) for x in str(v).split(".") if x.isdigit())


def version_codigo():
    try:
        v = (CODIGO / "actual.txt").read_text(encoding="utf-8").strip()
        if (CODIGO / v / "app.py").exists():
            return v
    except OSError:
        pass
    try:
        return (RECURSOS / "codigo" / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0"


def carpeta_codigo():
    try:
        v = (CODIGO / "actual.txt").read_text(encoding="utf-8").strip()
        if (CODIGO / v / "app.py").exists() and (CODIGO / v / "motor.py").exists():
            return CODIGO / v
    except OSError:
        pass
    return RECURSOS / "codigo"


def leer_manifest():
    try:
        with urllib.request.urlopen(f"{MANIFEST_URL}?t={int(time.time())}", timeout=15) as r:
            man = json.loads(r.read().decode("utf-8"))
        (DATOS / "manifest.json").write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
        return man
    except Exception:
        return None


def bajar_codigo(man):
    """Baja y prepara el código nuevo si lo hay. True si cambió."""
    nueva = str(man.get("version_codigo", "0"))
    if version_tupla(nueva) <= version_tupla(version_codigo()):
        return False
    if int(man.get("lanzador_minimo", 1)) > LANZADOR_VERSION:
        return False
    with urllib.request.urlopen(man["codigo_url"], timeout=60) as r:
        datos = r.read()
    if hashlib.sha256(datos).hexdigest() != man.get("sha256"):
        raise RuntimeError("el paquete bajado no coincide con su sha256")
    destino = CODIGO / nueva
    temporal = CODIGO / (nueva + ".tmp")
    shutil.rmtree(temporal, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        z.extractall(temporal)
    if not (temporal / "app.py").exists() or not (temporal / "motor.py").exists():
        raise RuntimeError("al paquete le faltan app.py o motor.py")
    shutil.rmtree(destino, ignore_errors=True)
    temporal.rename(destino)
    (CODIGO / "actual.txt").write_text(nueva, encoding="utf-8")
    # Deja solo la versión actual y la anterior.
    versiones = sorted((d for d in CODIGO.iterdir() if d.is_dir()), key=lambda d: version_tupla(d.name))
    for viejo in versiones[:-2]:
        shutil.rmtree(viejo, ignore_errors=True)
    return True


def revisar_servidor():
    """'eliminar', 'actualizado', 'reinstalar', 'ok' o 'sin_conexion'."""
    CODIGO.mkdir(parents=True, exist_ok=True)
    man = leer_manifest()
    if man is None:
        return "sin_conexion"
    if not man.get("activo", True):
        return "eliminar"
    try:
        if bajar_codigo(man):
            return "actualizado"
    except Exception as e:
        registrar(f"No pude bajar la actualización: {str(e)[:150]}")
        return "ok"
    if int(man.get("lanzador_minimo", 1)) > LANZADOR_VERSION:
        return "reinstalar"
    return "ok"


def mensaje_servidor():
    try:
        return json.loads((DATOS / "manifest.json").read_text(encoding="utf-8")).get("mensaje", "")
    except Exception:
        return ""


def registrar(texto):
    try:
        with (DATOS / "vigilante.log").open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  " + texto + "\n")
    except OSError:
        pass


def cargar(nombre):
    """Carga app.py / motor.py desde la carpeta de código (por ruta, para que gane la versión bajada)."""
    carpeta = carpeta_codigo()
    if str(carpeta) not in sys.path:
        sys.path.insert(0, str(carpeta))
    spec = importlib.util.spec_from_file_location(nombre, carpeta / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def comando_propio(*args):
    if CONGELADA:
        return [sys.executable, *args]
    return [sys.executable, str(Path(__file__).resolve()), *args]


def reiniciar(*args):
    """Abre de nuevo la app (para usar el código recién bajado) y termina este proceso."""
    extra = {"creationflags": SIN_VENTANA} if ES_WINDOWS else {"start_new_session": True}
    subprocess.Popen(comando_propio("--esperar", *args), **extra)
    os._exit(0)


# ---------------------------------------------------------------- Inicio con el sistema y accesos

def carpeta_especial(csidl):
    import ctypes
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return Path(buf.value)


def escritorio_linux():
    try:
        r = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5)
        if r.stdout.strip():
            return Path(r.stdout.strip())
    except Exception:
        pass
    return Path.home() / "Desktop"


def arranque_activado():
    if ES_WINDOWS:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                winreg.QueryValueEx(k, "VigilanteMEC")
                return True
        except OSError:
            return False
    return (Path.home() / ".config" / "autostart" / "vigilante-mec.desktop").exists()


def fijar_arranque(activo):
    cmd = " ".join(f'"{c}"' for c in comando_propio("--auto"))
    if ES_WINDOWS:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE) as k:
            if activo:
                winreg.SetValueEx(k, "VigilanteMEC", 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(k, "VigilanteMEC")
                except OSError:
                    pass
        return
    archivo = Path.home() / ".config" / "autostart" / "vigilante-mec.desktop"
    if activo:
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_text(f"[Desktop Entry]\nType=Application\nName={APP}\nExec={cmd}\n"
                           "X-GNOME-Autostart-enabled=true\n", encoding="utf-8")
    else:
        archivo.unlink(missing_ok=True)


def quitar_de_este_equipo(borrar_datos=True):
    """Quita accesos, inicio automático y archivos de la app (y sus datos)."""
    try:
        fijar_arranque(False)
    except Exception:
        pass
    if ES_WINDOWS:
        subprocess.run(["taskkill", "/IM", Path(sys.executable).name, "/T", "/F", "/FI", f"PID ne {os.getpid()}"],
                       capture_output=True, creationflags=SIN_VENTANA)
        import winreg
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Uninstall\VigilanteMEC")
        except OSError:
            pass
        for csidl in (0x10, 0x02):  # escritorio y menú Inicio
            (carpeta_especial(csidl) / f"{APP}.lnk").unlink(missing_ok=True)
        orden = f'timeout /t 3 /nobreak >nul & rmdir /s /q "{INSTALACION}"'
        if borrar_datos:
            orden += f' & rmdir /s /q "{DATOS}"'
        subprocess.Popen(["cmd", "/c", orden], creationflags=SIN_VENTANA, cwd=str(Path.home()))
        return
    # Cierra las otras copias (motor y su Chromium), pero no a este mismo proceso.
    r = subprocess.run(["pgrep", "-f", str(INSTALACION)], capture_output=True, text=True)
    for pid in r.stdout.split():
        if int(pid) != os.getpid():
            try:
                os.kill(int(pid), 9)
            except OSError:
                pass
    for archivo in (Path.home() / ".local" / "share" / "applications" / "vigilante-mec.desktop",
                    escritorio_linux() / "vigilante-mec.desktop",
                    Path.home() / ".local" / "bin" / "vigilante-mec"):
        try:
            archivo.unlink()
        except OSError:
            pass
    shutil.rmtree(INSTALACION, ignore_errors=True)
    if borrar_datos:
        shutil.rmtree(DATOS, ignore_errors=True)


def autodestruir():
    """El administrador desactivó la app en el servidor: se quita de este equipo."""
    texto = mensaje_servidor() or "El administrador desactivó Vigilante MEC."
    quitar_de_este_equipo(borrar_datos=True)
    try:
        import tkinter as tk
        from tkinter import messagebox
        tk.Tk().withdraw()
        messagebox.showinfo(APP, f"{texto}\n\nLa app se quitó de este equipo.")
    except Exception:
        pass
    os._exit(0)


def desinstalar():
    import tkinter as tk
    from tkinter import messagebox
    raiz = tk.Tk()
    raiz.withdraw()
    if not messagebox.askyesno(APP, "¿Quitar Vigilante MEC de este equipo?"):
        return
    borrar = messagebox.askyesno(APP, "¿Borrar también tus datos (configuración, sesión del MEC y registro)?")
    quitar_de_este_equipo(borrar_datos=borrar)
    messagebox.showinfo(APP, "Vigilante MEC se quitó de este equipo.")


# ---------------------------------------------------------------- Navegador (Linux sin Chrome)

def driver_playwright(*args):
    from playwright._impl._driver import compute_driver_executable, get_driver_env
    env = get_driver_env()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(DATOS / "navegadores")
    return subprocess.run([*compute_driver_executable(), *args], env=env).returncode


def probar_navegador():
    motor = cargar("motor")
    motor.configurar_log()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = motor.abrir_chrome(p, headless=True)
        ctx.close()
    print("NAVEGADOR_OK", flush=True)


def fusionar_config_instalador():
    """El instalador deja config_instalador.json (token, chats, rol); se mezcla sin pisar el resto."""
    nuevo = DATOS / "config_instalador.json"
    if not nuevo.exists():
        return
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    except Exception:
        cfg = {}
    instalador = json.loads(nuevo.read_text(encoding="utf-8"))
    if cfg.get("url_agenda"):
        instalador.pop("url_agenda", None)  # al reinstalar se mantiene el trámite actual
    cfg.update(instalador)
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    nuevo.unlink()
    if not ES_WINDOWS:
        os.chmod(CONFIG, 0o600)


# ---------------------------------------------------------------- Entrada

def main():
    DATOS.mkdir(parents=True, exist_ok=True)
    fusionar_config_instalador()
    argv = sys.argv[1:]
    if "--instalar-navegador" in argv:
        sys.exit(driver_playwright("install", "chromium"))
    if "--instalar-dependencias" in argv:
        sys.exit(driver_playwright("install-deps", "chromium"))
    if "--probar-navegador" in argv:
        probar_navegador()
        return
    if "--motor" in argv:
        cargar("motor").ejecutar()
        return
    if "--desinstalar" in argv:
        desinstalar()
        return

    # Una sola ventana a la vez (tras una actualización, espera a que se cierre la anterior).
    candado = socket.socket()
    for _ in range(30 if "--esperar" in argv else 1):
        try:
            candado.bind(("127.0.0.1", PUERTO_UNICO))
            break
        except OSError:
            time.sleep(0.5)
    else:
        import tkinter as tk
        from tkinter import messagebox
        tk.Tk().withdraw()
        messagebox.showinfo(APP, "Vigilante MEC ya está abierto.")
        return

    if revisar_servidor() == "eliminar":
        autodestruir()
    cargar("app").main(sys.modules[__name__], auto="--auto" in argv)
    candado.close()


if __name__ == "__main__":
    main()
