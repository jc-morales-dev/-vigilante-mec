"""Vigilante MEC - ventana de control (código actualizable desde el servidor).

La carga el lanzador con main(lz): lz es el módulo lanzador (rutas, servidor,
reinicio, inicio automático). Lanza el motor como proceso aparte (--motor),
muestra su estado leyendo el registro y deja cambiar la configuración local.
"""
import json
import os
import signal
import subprocess
import threading
import time
import urllib.parse
import urllib.request

APP = "Vigilante MEC"
REVISAR_SERVIDOR_CADA = 3600


def leer_config(lz):
    try:
        return json.loads(lz.CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def guardar_config(lz, cfg):
    lz.CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class Motor:
    def __init__(self, lz):
        self.lz = lz
        self.proc = None

    def vivo(self):
        return self.proc is not None and self.proc.poll() is None

    def encender(self):
        if self.vivo():
            return
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        errores = open(self.lz.DATOS / "motor_errores.log", "a", encoding="utf-8")
        extra = {"creationflags": self.lz.SIN_VENTANA} if self.lz.ES_WINDOWS else {"start_new_session": True}
        self.proc = subprocess.Popen(self.lz.comando_propio("--motor"), cwd=str(self.lz.DATOS), env=env,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=errores, **extra)
        errores.close()

    def apagar(self):
        if not self.vivo():
            self.proc = None
            return
        # Cierra también el Chrome que abrió el motor.
        if self.lz.ES_WINDOWS:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                           capture_output=True, creationflags=self.lz.SIN_VENTANA)
        else:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(5)
            except Exception:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except Exception:
                    pass
        self.proc = None


def main(lz, auto=False):
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, simpledialog, ttk

    motor = Motor(lz)
    raiz = tk.Tk()
    raiz.title(f"{APP} — versión {lz.version_codigo()}")
    raiz.geometry("760x650")
    raiz.minsize(620, 500)
    for icono in (lz.carpeta_codigo() / "icono.png", lz.RECURSOS / "icono.png"):
        try:
            raiz.iconphoto(True, tk.PhotoImage(file=str(icono)))
            break
        except Exception:
            pass

    cfg = leer_config(lz)
    estado = {"encendido": False, "reinicio_en": 0.0, "pos": 0, "aviso_reinstalar": False}
    colores = {"apagado": "#6b7280", "ok": "#2563eb", "cupo": "#16a34a", "aviso": "#d97706", "error": "#dc2626"}

    # --- Estado
    panel = tk.Frame(raiz, bg=colores["apagado"], padx=16, pady=12)
    panel.pack(fill="x")
    txt_estado = tk.Label(panel, text="Apagado", font=("Segoe UI", 18, "bold"), fg="white",
                          bg=colores["apagado"], anchor="w", justify="left", wraplength=700)
    txt_estado.pack(fill="x")
    txt_detalle = tk.Label(panel, text="Pulsa Encender para empezar a vigilar.", font=("Segoe UI", 10),
                           fg="white", bg=colores["apagado"], anchor="w", justify="left", wraplength=700)
    txt_detalle.pack(fill="x")

    def poner_estado(titulo, detalle, color):
        for w in (panel, txt_estado, txt_detalle):
            w.configure(bg=colores[color])
        txt_estado.configure(text=titulo)
        txt_detalle.configure(text=detalle)

    # --- Botones
    barra = ttk.Frame(raiz, padding=(12, 10))
    barra.pack(fill="x")

    def encender():
        if not leer_config(lz).get("telegram_token"):
            messagebox.showwarning(APP, "Falta el token del bot de Telegram (botón 'Cambiar token…').")
        estado["encendido"] = True
        estado["reinicio_en"] = 0.0
        motor.encender()
        poner_estado("Encendiendo…", "Se abre la ventana de Chrome del vigilante.", "ok")
        b_on.state(["disabled"])
        b_off.state(["!disabled"])

    def apagar():
        estado["encendido"] = False
        motor.apagar()
        poner_estado("Apagado", "El vigilante no está revisando.", "apagado")
        b_on.state(["!disabled"])
        b_off.state(["disabled"])

    def probar_telegram():
        def tarea():
            try:
                c = leer_config(lz)
                chats = [str(x) for x in c.get("chats_avisos", [])]
                url = f"https://api.telegram.org/bot{c['telegram_token']}/sendMessage"
                for chat in chats:
                    datos = urllib.parse.urlencode({"chat_id": chat, "text": "🧪 Prueba desde la app Vigilante MEC"})
                    urllib.request.urlopen(url, data=datos.encode(), timeout=20).read()
                raiz.after(0, lambda: messagebox.showinfo(APP, f"Mensaje de prueba enviado a {len(chats)} chat(s)."))
            except Exception as e:
                msg = str(e).splitlines()[0][:150] if str(e) else type(e).__name__
                raiz.after(0, lambda: messagebox.showerror(APP, f"No se pudo enviar: {msg}"))
        threading.Thread(target=tarea, daemon=True).start()

    def abrir_datos():
        if lz.ES_WINDOWS:
            os.startfile(lz.DATOS)
        else:
            subprocess.Popen(["xdg-open", str(lz.DATOS)])

    b_on = ttk.Button(barra, text="▶  Encender", command=encender)
    b_off = ttk.Button(barra, text="■  Apagar", command=apagar)
    b_on.pack(side="left")
    b_off.pack(side="left", padx=6)
    ttk.Button(barra, text="Probar Telegram", command=probar_telegram).pack(side="left", padx=6)
    ttk.Button(barra, text="Carpeta de datos", command=abrir_datos).pack(side="left")
    b_off.state(["disabled"])

    # --- Configuración (solo lo de este equipo; el resto lo ajusta el administrador desde el servidor)
    marco = ttk.LabelFrame(raiz, text="Configuración de este equipo", padding=10)
    marco.pack(fill="x", padx=12)
    marco.columnconfigure(1, weight=1)

    v_url = tk.StringVar(value=cfg.get("url_agenda", ""))
    v_auto = tk.BooleanVar(value=bool(cfg.get("encender_al_abrir", True)))
    v_arranque = tk.BooleanVar(value=lz.arranque_activado())
    v_telegram = tk.BooleanVar(value=bool(cfg.get("telegram_activo", True)))

    ttk.Label(marco, text="Trámite en Agenda:").grid(row=0, column=0, sticky="w")
    ttk.Entry(marco, textvariable=v_url).grid(row=0, column=1, columnspan=3, sticky="ew", pady=2)
    ttk.Label(marco, text="(se busca solo al iniciar sesión; puedes dejarlo vacío)", foreground="#6b7280").grid(
        row=1, column=1, columnspan=3, sticky="w")
    ttk.Checkbutton(marco, text="Encender el vigilante al abrir la app", variable=v_auto).grid(
        row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
    ttk.Checkbutton(marco, text="Abrir la app al iniciar el " + ("Windows" if lz.ES_WINDOWS else "equipo"),
                    variable=v_arranque).grid(row=3, column=0, columnspan=2, sticky="w")
    ttk.Checkbutton(marco, text="Enviar avisos a Telegram desde este equipo (si lo quitas, avisa el otro PC)",
                    variable=v_telegram).grid(row=4, column=0, columnspan=4, sticky="w")
    txt_token = ttk.Label(marco)
    txt_token.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def refrescar_token():
        c = leer_config(lz)
        if not c.get("telegram_token"):
            tg = "Telegram: FALTA el token"
        elif not c.get("telegram_activo", True):
            tg = "Telegram: DESACTIVADO en este equipo"
        else:
            tg = "Telegram: activo ✓"
        rol = "principal" if c.get("rol", "principal") == "principal" else "respaldo"
        txt_token.configure(text=f"{tg}   ·   Este equipo es el {rol}")

    def cambiar_token():
        nuevo = simpledialog.askstring(APP, "Pega el token del bot de Telegram:", show="*", parent=raiz)
        if nuevo:
            c = leer_config(lz)
            c["telegram_token"] = nuevo.strip().strip('"')
            guardar_config(lz, c)
            refrescar_token()
            reiniciar_si_encendido()

    def guardar():
        url = v_url.get().strip()
        if url and not url.startswith("https://bpmgob.mec.gub.uy/etapas/ejecutar/"):
            messagebox.showerror(APP, "El enlace del trámite debe ser de https://bpmgob.mec.gub.uy/etapas/ejecutar/…")
            return
        c = leer_config(lz)
        if c.get("telegram_activo", True) and not v_telegram.get() and not messagebox.askyesno(
                APP, "Este equipo dejará de mandar avisos a Telegram.\n\nLos avisos los mandará el otro PC, "
                     "así que asegúrate de que esté encendido y vigilando. ¿Seguir?"):
            return
        c.update(url_agenda=url, encender_al_abrir=bool(v_auto.get()), telegram_activo=bool(v_telegram.get()))
        guardar_config(lz, c)
        refrescar_token()
        try:
            lz.fijar_arranque(bool(v_arranque.get()))
        except Exception as e:
            messagebox.showwarning(APP, f"No pude cambiar el inicio automático: {e}")
        reiniciar_si_encendido()
        messagebox.showinfo(APP, "Configuración guardada." + (" El vigilante se reinició." if estado["encendido"] else ""))

    def reiniciar_si_encendido():
        if estado["encendido"]:
            motor.apagar()
            encender()

    ttk.Button(marco, text="Cambiar token…", command=cambiar_token).grid(row=5, column=2, sticky="e", pady=(6, 0))
    ttk.Button(marco, text="Guardar", command=guardar).grid(row=5, column=3, sticky="e", padx=(6, 0), pady=(6, 0))
    refrescar_token()

    # --- Registro
    ttk.Label(raiz, text="Registro:", padding=(12, 8, 12, 0)).pack(anchor="w")
    caja = scrolledtext.ScrolledText(raiz, height=11, font=("Consolas", 9), state="disabled", wrap="word")
    caja.pack(fill="both", expand=True, padx=12)
    caja.tag_configure("cupo", foreground="#15803d", font=("Consolas", 9, "bold"))
    caja.tag_configure("error", foreground="#b91c1c")
    caja.tag_configure("aviso", foreground="#b45309")
    pie = ttk.Label(raiz, text="Se actualiza sola desde el servidor del administrador, que también puede "
                               "desactivarla y quitarla de este equipo.", foreground="#6b7280", padding=(12, 4, 12, 8))
    pie.pack(anchor="w")

    def anotar(linea):
        etiqueta = ()
        if "CUPOS:" in linea or "MODO RESERVA" in linea or "Cupo detectado" in linea:
            etiqueta = ("cupo",)
        elif "Error" in linea or "se detuvo" in linea or "Se cerró" in linea or "No pude" in linea:
            etiqueta = ("error",)
        elif "sesión" in linea.lower() and "OK" not in linea:
            etiqueta = ("aviso",)
        caja.configure(state="normal")
        caja.insert("end", linea + "\n", etiqueta)
        if int(caja.index("end-1c").split(".")[0]) > 600:
            caja.delete("1.0", "100.0")
        caja.see("end")
        caja.configure(state="disabled")

    def alerta_cupos(fechas):
        poner_estado("🚨 ¡HAY CUPOS!", f"Fechas: {fechas}\nElige día y horario en la ventana de Chrome del vigilante.",
                     "cupo")
        for i in range(4):
            raiz.after(i * 400, raiz.bell)
        raiz.deiconify()

    def interpretar(linea):
        msg = linea[21:] if len(linea) > 21 and linea[4] == "-" else linea
        hora = linea[11:19] if len(linea) > 19 else ""
        if msg.startswith("Sin cupos"):
            poner_estado("Vigilando — sin cupos", f"Última revisión completa: {hora}. "
                         "Entre revisiones hace sondeos rápidos.", "ok")
        elif msg.startswith("CUPOS:"):
            alerta_cupos(msg[6:].strip())
        elif msg.startswith("MODO RESERVA"):
            poner_estado("🚨 Modo reserva", "La ventana de Chrome del vigilante está quieta con el calendario: "
                         "elige día y horario ahí.", "cupo")
        elif msg.startswith("Esperando a que inicies sesión") or msg.startswith("Sesión caída"):
            poner_estado("🔒 Inicia sesión en el MEC", "Hazlo en la ventana de Chrome que abrió el vigilante. "
                         "Cuando entres, sigue solo.", "aviso")
        elif msg.startswith("No encontré ningún trámite"):
            poner_estado("📋 Falta un trámite en la Agenda", "En la ventana de Chrome del vigilante abre un trámite "
                         "nuevo hasta el paso Agenda. Lo detecta solo.", "aviso")
        elif msg.startswith("Trámite en Agenda"):
            v_url.set(msg.split(": ", 1)[-1].strip())
        elif msg.startswith("Sesión OK"):
            poner_estado("Vigilando…", "Sesión del MEC iniciada.", "ok")
        elif msg.startswith("Error en revisión"):
            poner_estado("Problema al revisar", msg + "\nReintenta solo.", "aviso")
        elif "se detuvo" in msg or msg.startswith("Se cerró la ventana"):
            poner_estado("El vigilante se detuvo", msg + "\nSe vuelve a encender en 10 s.", "error")

    def leer_registro(primera=False):
        registro = lz.DATOS / "vigilante.log"
        try:
            tam = registro.stat().st_size
        except OSError:
            return
        if tam < estado["pos"]:
            estado["pos"] = 0
        if primera:
            estado["pos"] = max(0, tam - 20000)
        with registro.open("rb") as f:
            f.seek(estado["pos"])
            datos = f.read()
        corte = datos.rfind(b"\n") + 1
        if not corte:
            return
        estado["pos"] += corte
        lineas = datos[:corte].decode("utf-8", "replace").splitlines()
        if primera:
            lineas = lineas[1:]  # la primera puede estar cortada
        for l in lineas:
            if l.strip():
                anotar(l)
                if not primera:
                    interpretar(l)

    def vigilar_motor():
        leer_registro()
        if estado["encendido"] and not motor.vivo():
            ahora = time.time()
            if not estado["reinicio_en"]:
                estado["reinicio_en"] = ahora + 10
                poner_estado("El vigilante se detuvo", "Se vuelve a encender en 10 s…", "error")
            elif ahora >= estado["reinicio_en"]:
                estado["reinicio_en"] = 0.0
                motor.encender()
        raiz.after(1000, vigilar_motor)

    # --- Servidor: actualizaciones y desactivación
    def revisar_servidor():
        def tarea():
            resultado = lz.revisar_servidor()
            raiz.after(0, lambda: aplicar(resultado))
        threading.Thread(target=tarea, daemon=True).start()
        raiz.after(REVISAR_SERVIDOR_CADA * 1000, revisar_servidor)

    def aplicar(resultado):
        if resultado == "eliminar":
            motor.apagar()
            lz.autodestruir()
        elif resultado == "actualizado":
            lz.registrar(f"Actualización descargada: versión {lz.version_codigo()}. Reiniciando la app.")
            encendido = estado["encendido"]
            motor.apagar()
            lz.reiniciar(*(["--auto"] if encendido else []))
        elif resultado == "reinstalar" and not estado["aviso_reinstalar"]:
            estado["aviso_reinstalar"] = True
            messagebox.showinfo(APP, "Hay una versión nueva que necesita reinstalar la app. "
                                     "Pide el instalador nuevo al administrador.")

    def cerrar():
        if estado["encendido"] and not messagebox.askyesno(
                APP, "El vigilante está encendido. ¿Apagarlo y cerrar la app?\n\n"
                     "(Si solo quieres quitarla de en medio, minimízala.)"):
            return
        motor.apagar()
        raiz.destroy()

    raiz.protocol("WM_DELETE_WINDOW", cerrar)
    leer_registro(primera=True)
    if auto or cfg.get("encender_al_abrir", True):
        raiz.after(500, encender)
    raiz.after(1000, vigilar_motor)
    raiz.after(REVISAR_SERVIDOR_CADA * 1000, revisar_servidor)
    raiz.mainloop()
