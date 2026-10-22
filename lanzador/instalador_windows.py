"""Instalador de Vigilante MEC para Windows (por usuario, sin permisos de administrador).

Lleva dentro app.zip (el lanzador que genera PyInstaller) y, si se construyó
para una persona, config_instalador.json (token, chats y rol). Copia la app a
%LOCALAPPDATA%\\Programs\\VigilanteMEC, crea los accesos y la entrada en
"Agregar o quitar programas".
"""
import ctypes
import os
import shutil
import subprocess
import sys
import tkinter as tk
import winreg
import zipfile
from pathlib import Path
from tkinter import messagebox, ttk

APP = "Vigilante MEC"
RECURSOS = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
DESTINO = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "VigilanteMEC"
DATOS = Path(os.environ["LOCALAPPDATA"]) / "VigilanteMEC"
EXE = DESTINO / "VigilanteMEC.exe"
SIN_VENTANA = 0x08000000
CLAVE_DESINSTALAR = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\VigilanteMEC"
AVISO = ("Vigila los cupos de la Agenda del MEC y avisa por Telegram.\n\n"
         "Importante: la app se actualiza sola desde el servidor del administrador "
         "(GitHub jc-morales-dev/-vigilante-mec). El administrador también puede desactivarla "
         "a distancia: en ese caso se quita sola de este equipo junto con sus datos. "
         "Solo toca sus propias carpetas y accesos.")


def carpeta_especial(csidl):
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return Path(buf.value)


def crear_acceso(ruta):
    p = lambda s: str(s).replace("'", "''")
    orden = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{p(ruta)}');"
             f"$s.TargetPath='{p(EXE)}';$s.WorkingDirectory='{p(DESTINO)}';"
             f"$s.IconLocation='{p(EXE)},0';$s.Description='{APP}';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", orden], check=True,
                   capture_output=True, creationflags=SIN_VENTANA)


def app_abierta():
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq VigilanteMEC.exe", "/NH"],
                       capture_output=True, text=True, creationflags=SIN_VENTANA)
    return "VigilanteMEC.exe" in r.stdout


def instalar(escritorio, arranque, abrir, paso):
    if app_abierta():
        if not messagebox.askyesno(APP, "Vigilante MEC está abierto. Para instalar hay que cerrarlo "
                                        "(también su vigilante y su Chrome). ¿Cerrarlo ahora?"):
            return False
        subprocess.run(["taskkill", "/IM", "VigilanteMEC.exe", "/T", "/F"],
                       capture_output=True, creationflags=SIN_VENTANA)

    paso("Copiando archivos…")
    if DESTINO.exists():
        shutil.rmtree(DESTINO, ignore_errors=True)
    DESTINO.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RECURSOS / "app.zip") as z:
        z.extractall(DESTINO)
    if (RECURSOS / "config_instalador.json").exists():
        DATOS.mkdir(parents=True, exist_ok=True)
        shutil.copy(RECURSOS / "config_instalador.json", DATOS / "config_instalador.json")

    paso("Creando accesos directos…")
    crear_acceso(carpeta_especial(0x02) / f"{APP}.lnk")  # menú Inicio
    acceso_escritorio = carpeta_especial(0x10) / f"{APP}.lnk"
    if escritorio:
        crear_acceso(acceso_escritorio)
    else:
        acceso_escritorio.unlink(missing_ok=True)

    paso("Registrando la app…")
    tam_kb = sum(f.stat().st_size for f in DESTINO.rglob("*") if f.is_file()) // 1024
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CLAVE_DESINSTALAR) as k:
        for nombre, valor in (("DisplayName", APP), ("DisplayVersion", "1"), ("Publisher", "Vigilante MEC"),
                              ("DisplayIcon", f'"{EXE}",0'), ("InstallLocation", str(DESTINO)),
                              ("UninstallString", f'"{EXE}" --desinstalar')):
            winreg.SetValueEx(k, nombre, 0, winreg.REG_SZ, valor)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, tam_kb)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                        0, winreg.KEY_SET_VALUE) as k:
        if arranque:
            winreg.SetValueEx(k, "VigilanteMEC", 0, winreg.REG_SZ, f'"{EXE}" --auto')
        else:
            try:
                winreg.DeleteValue(k, "VigilanteMEC")
            except OSError:
                pass

    if abrir:
        subprocess.Popen([str(EXE)], cwd=str(DESTINO))
    return True


def main():
    raiz = tk.Tk()
    raiz.title(f"Instalar {APP}")
    raiz.geometry("500x380")
    raiz.resizable(False, False)
    try:
        raiz.iconphoto(True, tk.PhotoImage(file=str(RECURSOS / "icono.png")))
    except Exception:
        pass
    marco = ttk.Frame(raiz, padding=20)
    marco.pack(fill="both", expand=True)
    ttk.Label(marco, text=f"Instalar {APP}", font=("Segoe UI", 16, "bold")).pack(anchor="w")
    ttk.Label(marco, text=AVISO, wraplength=460, justify="left").pack(anchor="w", pady=(6, 10))
    v_acepto = tk.BooleanVar(value=False)
    v_esc = tk.BooleanVar(value=True)
    v_arr = tk.BooleanVar(value=True)
    v_abrir = tk.BooleanVar(value=True)
    ttk.Checkbutton(marco, text="Lo entiendo y acepto", variable=v_acepto,
                    command=lambda: boton.state(["!disabled"] if v_acepto.get() else ["disabled"])).pack(anchor="w")
    ttk.Separator(marco).pack(fill="x", pady=8)
    ttk.Checkbutton(marco, text="Crear icono en el escritorio", variable=v_esc).pack(anchor="w")
    ttk.Checkbutton(marco, text="Abrir la app al iniciar Windows", variable=v_arr).pack(anchor="w")
    ttk.Checkbutton(marco, text="Abrir Vigilante MEC al terminar", variable=v_abrir).pack(anchor="w")
    txt = ttk.Label(marco, text="")
    txt.pack(anchor="w", pady=(10, 0))

    def paso(t):
        txt.configure(text=t)
        raiz.update()

    def pulsar():
        boton.state(["disabled"])
        try:
            if instalar(v_esc.get(), v_arr.get(), v_abrir.get(), paso):
                messagebox.showinfo(APP, "Instalación terminada.")
                raiz.destroy()
                return
        except Exception as e:
            messagebox.showerror(APP, f"No se pudo instalar: {e}")
        paso("")
        boton.state(["!disabled"])

    boton = ttk.Button(marco, text="Instalar", command=pulsar)
    boton.pack(anchor="e", side="bottom")
    boton.state(["disabled"])
    raiz.mainloop()


if __name__ == "__main__":
    main()
