"""Vigilante MEC - ventana de control (código actualizable desde el servidor).

La carga el lanzador con main(lz): lz es el módulo lanzador (rutas, servidor,
reinicio, inicio automático). Lanza el motor como proceso aparte (--motor),
muestra su estado leyendo el registro y deja cambiar la configuración local.
"""
import json
import os
import re
import signal
import subprocess
import threading
import time
import urllib.parse
import urllib.request

APP = "Vigilante MEC"
REVISAR_SERVIDOR_CADA = 3600

# Tema oscuro
FONDO = "#0f172a"
TARJETA = "#1e293b"
BORDE = "#334155"
TEXTO = "#e2e8f0"
TENUE = "#94a3b8"
VERDE = "#22c55e"
ROJO = "#ef4444"
AMBAR = "#f59e0b"
AZUL = "#3b82f6"
GRIS = "#64748b"


def barra_oscura(ventana):
    """Barra de título oscura en Windows 10/11 (en Linux la pone el tema del sistema)."""
    try:
        import ctypes
        ventana.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(ventana.winfo_id())
        valor = ctypes.c_int(1)
        for atributo in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (y su número antiguo)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, atributo, ctypes.byref(valor),
                                                          ctypes.sizeof(valor)) == 0:
                break
    except Exception:
        pass


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
    from tkinter import font as tkfont, messagebox, simpledialog

    motor = Motor(lz)
    raiz = tk.Tk()
    raiz.title(APP)
    raiz.geometry("720x450")
    raiz.minsize(600, 430)
    raiz.configure(bg=FONDO)
    if lz.ES_WINDOWS:
        barra_oscura(raiz)
    for icono in (lz.carpeta_codigo() / "icono.png", lz.RECURSOS / "icono.png"):
        try:
            raiz.iconphoto(True, tk.PhotoImage(file=str(icono)))
            break
        except Exception:
            pass

    familias = set(tkfont.families())
    letra = next((f for f in ("Segoe UI", "Ubuntu", "Cantarell", "DejaVu Sans") if f in familias), "TkDefaultFont")
    mono = next((f for f in ("Consolas", "DejaVu Sans Mono", "Ubuntu Mono") if f in familias), "TkFixedFont")

    def F(tam, peso="normal"):
        return (letra, tam, peso)

    cfg = leer_config(lz)
    estado = {"encendido": False, "reinicio_en": 0.0, "pos": 0, "aviso_reinstalar": False,
              "detalles": False, "parpadeo": 0}

    # ------------------------------------------------------------ piezas reutilizables
    def boton(padre, texto, comando, color=TARJETA, fg=TEXTO, tam=10, peso="normal", px=14, py=7):
        b = tk.Label(padre, text=texto, bg=color, fg=fg, font=F(tam, peso), padx=px, pady=py, cursor="hand2")
        b._color = color

        def entrar(_):
            b.configure(bg=aclarar(b._color))

        def salir(_):
            b.configure(bg=b._color)
        b.bind("<Enter>", entrar)
        b.bind("<Leave>", salir)
        b.bind("<Button-1>", lambda _: comando())
        return b

    def colorear_boton(b, color, texto=None):
        b._color = color
        b.configure(bg=color, **({"text": texto} if texto else {}))

    def aclarar(color):
        r, g, b_ = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        return "#%02x%02x%02x" % tuple(min(255, int(c + (255 - c) * 0.15)) for c in (r, g, b_))

    def tarjeta(padre):
        return tk.Frame(padre, bg=TARJETA, highlightbackground=BORDE, highlightthickness=1)

    # ------------------------------------------------------------ cabecera
    cabecera = tk.Frame(raiz, bg=FONDO, padx=22, pady=14)
    cabecera.pack(fill="x")
    logo = tk.Canvas(cabecera, width=30, height=30, bg=FONDO, highlightthickness=0)
    logo.create_oval(2, 2, 28, 28, outline=AZUL, width=3)
    logo.create_oval(10, 10, 20, 20, fill=VERDE, outline="")
    logo.pack(side="left")
    tk.Label(cabecera, text=APP, bg=FONDO, fg=TEXTO, font=F(15, "bold")).pack(side="left", padx=(10, 6))
    tk.Label(cabecera, text=f"v{lz.version_codigo()}", bg=FONDO, fg=GRIS, font=F(9)).pack(side="left", pady=(5, 0))
    boton(cabecera, "⚙  Ajustes", lambda: abrir_ajustes(), color=FONDO, fg=TENUE).pack(side="right")

    # ------------------------------------------------------------ estado
    panel = tarjeta(raiz)
    panel.pack(fill="x", padx=22)
    interior = tk.Frame(panel, bg=TARJETA, padx=22, pady=20)
    interior.pack(fill="x")
    punto = tk.Canvas(interior, width=26, height=26, bg=TARJETA, highlightthickness=0)
    punto.grid(row=0, column=0, rowspan=2, sticky="n", pady=(4, 0))
    circulo = punto.create_oval(3, 3, 23, 23, fill=GRIS, outline="")
    txt_estado = tk.Label(interior, text="Apagado", bg=TARJETA, fg=TEXTO, font=F(19, "bold"), anchor="w")
    txt_estado.grid(row=0, column=1, sticky="w", padx=(14, 0))
    txt_detalle = tk.Label(interior, text="Pulsa Encender para empezar a vigilar.", bg=TARJETA, fg=TENUE,
                           font=F(10), anchor="w", justify="left", wraplength=560)
    txt_detalle.grid(row=1, column=1, sticky="w", padx=(14, 0), pady=(2, 0))

    def poner_estado(titulo, detalle, color):
        punto.itemconfigure(circulo, fill=color)
        txt_estado.configure(text=titulo, fg=TEXTO if color in (GRIS, AZUL, VERDE) else color)
        txt_detalle.configure(text=detalle)

    def parpadear(veces=10):
        """Hace parpadear el panel cuando hay cupo, para que se vea desde lejos."""
        estado["parpadeo"] = veces

        def paso():
            if estado["parpadeo"] <= 0:
                for w in (panel, interior, punto, txt_estado, txt_detalle):
                    w.configure(bg=TARJETA)
                return
            color = "#14532d" if estado["parpadeo"] % 2 else TARJETA
            for w in (interior, punto, txt_estado, txt_detalle):
                w.configure(bg=color)
            estado["parpadeo"] -= 1
            raiz.after(450, paso)
        paso()

    # ------------------------------------------------------------ botón grande
    zona = tk.Frame(raiz, bg=FONDO, pady=18)
    zona.pack(fill="x")
    b_principal = boton(zona, "▶   ENCENDER", lambda: alternar(), color=VERDE, fg="#052e16", tam=14,
                        peso="bold", px=48, py=12)
    b_principal.pack()

    def alternar():
        apagar() if estado["encendido"] else encender()

    def encender():
        if not leer_config(lz).get("telegram_token"):
            messagebox.showwarning(APP, "Falta el token del bot de Telegram (Ajustes → Cambiar token).")
        estado["encendido"] = True
        estado["reinicio_en"] = 0.0
        motor.encender()
        poner_estado("Encendiendo…", "Se abre la ventana de Chrome del vigilante.", AZUL)
        colorear_boton(b_principal, "#334155", "■   APAGAR")
        b_principal.configure(fg=TEXTO)

    def apagar():
        estado["encendido"] = False
        motor.apagar()
        poner_estado("Apagado", "El vigilante no está revisando. Pulsa Encender para empezar.", GRIS)
        colorear_boton(b_principal, VERDE, "▶   ENCENDER")
        b_principal.configure(fg="#052e16")

    # ------------------------------------------------------------ tarjetas de resumen
    fila = tk.Frame(raiz, bg=FONDO)
    fila.pack(fill="x", padx=22)
    resumen = {}
    for i, (clave, titulo) in enumerate((("tramite", "TRÁMITE"), ("telegram", "TELEGRAM"), ("pc", "ESTE EQUIPO"))):
        fila.columnconfigure(i, weight=1, uniform="t")
        t = tarjeta(fila)
        t.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 2 else 6))
        tk.Label(t, text=titulo, bg=TARJETA, fg=GRIS, font=F(8, "bold"), anchor="w").pack(
            fill="x", padx=14, pady=(10, 0))
        valor = tk.Label(t, text="—", bg=TARJETA, fg=TEXTO, font=F(12, "bold"), anchor="w")
        valor.pack(fill="x", padx=14)
        nota = tk.Label(t, text="", bg=TARJETA, fg=TENUE, font=F(9), anchor="w")
        nota.pack(fill="x", padx=14, pady=(0, 10))
        resumen[clave] = (valor, nota)

    def refrescar_resumen():
        c = leer_config(lz)
        m = re.search(r"/ejecutar/(\d+)", c.get("url_agenda", ""))
        resumen["tramite"][0].configure(text=f"Nº {m.group(1)}" if m else "Se busca solo", fg=TEXTO)
        resumen["tramite"][1].configure(text="en la Agenda del MEC" if m else "al iniciar sesión")
        if not c.get("telegram_token"):
            resumen["telegram"][0].configure(text="Falta token", fg=ROJO)
            resumen["telegram"][1].configure(text="ve a Ajustes")
        elif not c.get("telegram_activo", True):
            resumen["telegram"][0].configure(text="Desactivado", fg=AMBAR)
            resumen["telegram"][1].configure(text="avisa el otro equipo")
        else:
            resumen["telegram"][0].configure(text="Activo ✓", fg=VERDE)
            resumen["telegram"][1].configure(text=f"avisa a {len(c.get('chats_avisos', []))} persona(s)")
        principal = c.get("rol", "principal") == "principal"
        resumen["pc"][0].configure(text="Principal" if principal else "Respaldo", fg=TEXTO)
        resumen["pc"][1].configure(text="avisa siempre" if principal else "avisa si el principal no puede")

    # ------------------------------------------------------------ detalles (registro técnico)
    pie = tk.Frame(raiz, bg=FONDO, padx=22, pady=10)
    pie.pack(fill="x")
    b_detalles = boton(pie, "Ver detalles ▾", lambda: alternar_detalles(), color=FONDO, fg=TENUE, px=0)
    b_detalles.pack(side="right")
    tk.Label(pie, text="Se actualiza sola desde el servidor del administrador.", bg=FONDO, fg=GRIS,
             font=F(8)).pack(side="left")

    marco_log = tk.Frame(raiz, bg=FONDO, padx=22)
    caja = tk.Text(marco_log, height=10, bg="#020617", fg=TENUE, insertbackground=TEXTO, relief="flat",
                   font=(mono, 9), wrap="word", state="disabled", padx=10, pady=8, highlightthickness=1,
                   highlightbackground=BORDE)
    barra = tk.Scrollbar(marco_log, command=caja.yview)
    caja.configure(yscrollcommand=barra.set)
    barra.pack(side="right", fill="y")
    caja.pack(fill="both", expand=True, pady=(0, 16))
    caja.tag_configure("cupo", foreground=VERDE, font=(mono, 9, "bold"))
    caja.tag_configure("error", foreground=ROJO)
    caja.tag_configure("aviso", foreground=AMBAR)

    def alternar_detalles():
        estado["detalles"] = not estado["detalles"]
        if estado["detalles"]:
            marco_log.pack(fill="both", expand=True)
            b_detalles.configure(text="Ocultar detalles ▴")
            raiz.geometry(f"{raiz.winfo_width()}x{max(raiz.winfo_height(), 660)}")
            caja.see("end")
        else:
            marco_log.pack_forget()
            b_detalles.configure(text="Ver detalles ▾")
            raiz.geometry(f"{raiz.winfo_width()}x450")

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

    # ------------------------------------------------------------ ventana de ajustes
    def abrir_ajustes():
        c = leer_config(lz)
        v = tk.Toplevel(raiz)
        v.title(f"{APP} — Ajustes")
        v.configure(bg=FONDO)
        v.resizable(False, False)
        v.transient(raiz)
        if lz.ES_WINDOWS:
            barra_oscura(v)
        cuerpo = tk.Frame(v, bg=FONDO, padx=24, pady=20)
        cuerpo.pack(fill="both")
        tk.Label(cuerpo, text="Ajustes de este equipo", bg=FONDO, fg=TEXTO, font=F(14, "bold")).pack(anchor="w")

        tk.Label(cuerpo, text="Trámite en la Agenda", bg=FONDO, fg=TENUE, font=F(9, "bold")).pack(
            anchor="w", pady=(16, 2))
        v_url = tk.StringVar(value=c.get("url_agenda", ""))
        tk.Entry(cuerpo, textvariable=v_url, width=58, bg=TARJETA, fg=TEXTO, insertbackground=TEXTO,
                 relief="flat", font=F(10), highlightthickness=1, highlightbackground=BORDE,
                 highlightcolor=AZUL).pack(anchor="w", ipady=5)
        tk.Label(cuerpo, text="Se busca solo al iniciar sesión en el MEC. Puedes dejarlo vacío.", bg=FONDO,
                 fg=GRIS, font=F(8)).pack(anchor="w", pady=(2, 10))

        def casilla(texto, valor):
            var = tk.BooleanVar(value=valor)
            tk.Checkbutton(cuerpo, text=texto, variable=var, bg=FONDO, fg=TEXTO, selectcolor=TARJETA,
                           activebackground=FONDO, activeforeground=TEXTO, font=F(10), anchor="w",
                           highlightthickness=0, bd=0).pack(anchor="w", pady=2)
            return var

        v_auto = casilla("Encender el vigilante al abrir la app", bool(c.get("encender_al_abrir", True)))
        v_arranque = casilla("Abrir la app al iniciar el " + ("Windows" if lz.ES_WINDOWS else "equipo"),
                             lz.arranque_activado())
        principal = c.get("rol", "principal") == "principal"
        v_telegram = None
        if principal:
            # Solo el principal puede callarse: el respaldo es quien avisa cuando el principal no lo hace.
            v_telegram = casilla("Enviar avisos a Telegram desde este equipo", bool(c.get("telegram_activo", True)))
            tk.Label(cuerpo, text="Si lo quitas, los avisos los manda el otro equipo.", bg=FONDO, fg=GRIS,
                     font=F(8)).pack(anchor="w", padx=(24, 0))

        acciones = tk.Frame(cuerpo, bg=FONDO)
        acciones.pack(fill="x", pady=(16, 0))
        boton(acciones, "Cambiar token", lambda: cambiar_token(v)).pack(side="left")
        boton(acciones, "Probar Telegram", probar_telegram).pack(side="left", padx=6)
        boton(acciones, "Carpeta de datos", abrir_datos).pack(side="left")

        def guardar():
            url = v_url.get().strip()
            if url and not url.startswith("https://bpmgob.mec.gub.uy/etapas/ejecutar/"):
                messagebox.showerror(APP, "El enlace debe ser de https://bpmgob.mec.gub.uy/etapas/ejecutar/…",
                                     parent=v)
                return
            nuevo = leer_config(lz)
            tg = bool(v_telegram.get()) if v_telegram is not None else True
            if nuevo.get("telegram_activo", True) and not tg and not messagebox.askyesno(
                    APP, "Este equipo dejará de mandar avisos a Telegram.\n\nLos mandará el otro equipo, así que "
                         "asegúrate de que esté encendido y vigilando. ¿Seguir?", parent=v):
                return
            nuevo.update(url_agenda=url, encender_al_abrir=bool(v_auto.get()), telegram_activo=tg)
            guardar_config(lz, nuevo)
            try:
                lz.fijar_arranque(bool(v_arranque.get()))
            except Exception as e:
                messagebox.showwarning(APP, f"No pude cambiar el inicio automático: {e}", parent=v)
            refrescar_resumen()
            reiniciar_si_encendido()
            v.destroy()

        pie_v = tk.Frame(cuerpo, bg=FONDO)
        pie_v.pack(fill="x", pady=(22, 0))
        boton(pie_v, "Guardar", guardar, color=AZUL, fg="white", peso="bold").pack(side="right")
        boton(pie_v, "Cancelar", v.destroy).pack(side="right", padx=8)
        v.grab_set()

    def cambiar_token(padre):
        nuevo = simpledialog.askstring(APP, "Pega el token del bot de Telegram:", show="*", parent=padre)
        if nuevo:
            c = leer_config(lz)
            c["telegram_token"] = nuevo.strip().strip('"')
            guardar_config(lz, c)
            refrescar_resumen()
            reiniciar_si_encendido()

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

    def reiniciar_si_encendido():
        if estado["encendido"]:
            motor.apagar()
            encender()

    # ------------------------------------------------------------ lectura del registro del motor
    def alerta_cupos(fechas):
        poner_estado("¡HAY CUPO!", f"Fechas: {fechas}\nVe a la ventana de Chrome del vigilante y elige día y horario.",
                     VERDE)
        txt_estado.configure(fg=VERDE)
        parpadear()
        for i in range(4):
            raiz.after(i * 400, raiz.bell)
        raiz.deiconify()

    def interpretar(linea):
        msg = linea[21:] if len(linea) > 21 and linea[4] == "-" else linea
        hora = linea[11:19] if len(linea) > 19 else ""
        if msg.startswith("Sin cupos"):
            poner_estado("Vigilando — sin cupos por ahora", f"Última revisión completa: {hora}. "
                         "Entre revisiones mira cada pocos segundos.", VERDE)
        elif msg.startswith("CUPOS:"):
            alerta_cupos(msg[6:].strip())
        elif msg.startswith("MODO RESERVA"):
            poner_estado("¡HAY CUPO! — reserva ahora", "La ventana de Chrome del vigilante está quieta con el "
                         "calendario: elige día y horario ahí.", VERDE)
            txt_estado.configure(fg=VERDE)
        elif msg.startswith("Esperando a que inicies sesión") or msg.startswith("Sesión caída"):
            poner_estado("Inicia sesión en el MEC", "Hazlo en la ventana de Chrome que abrió el vigilante. "
                         "Cuando entres, sigue solo.", AMBAR)
        elif msg.startswith("No encontré ningún trámite"):
            poner_estado("Falta un trámite en la Agenda", "En la ventana de Chrome del vigilante abre un trámite "
                         "nuevo hasta el paso Agenda. Lo detecta solo.", AMBAR)
        elif msg.startswith("Trámite en Agenda"):
            refrescar_resumen()
        elif msg.startswith("Sesión OK"):
            poner_estado("Vigilando…", "Sesión del MEC iniciada.", VERDE)
        elif msg.startswith("Error en revisión"):
            poner_estado("Problema al revisar", "Reintenta solo. Si sigue, mira «Ver detalles».", AMBAR)
        elif "se detuvo" in msg or msg.startswith("Se cerró la ventana"):
            poner_estado("El vigilante se detuvo", "Se vuelve a encender solo en 10 segundos.", ROJO)

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
                poner_estado("El vigilante se detuvo", "Se vuelve a encender solo en 10 segundos…", ROJO)
            elif ahora >= estado["reinicio_en"]:
                estado["reinicio_en"] = 0.0
                motor.encender()
        raiz.after(1000, vigilar_motor)

    # ------------------------------------------------------------ servidor: actualizaciones y desactivación
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
    refrescar_resumen()
    leer_registro(primera=True)
    if auto or cfg.get("encender_al_abrir", True):
        raiz.after(500, encender)
    raiz.after(1000, vigilar_motor)
    raiz.after(REVISAR_SERVIDOR_CADA * 1000, revisar_servidor)
    raiz.mainloop()
