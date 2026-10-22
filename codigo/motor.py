"""
Vigilante de cupos - MEC Inscripción de partidas extranjeras (motor).

Recarga la etapa "Agenda" del trámite, marca "Oficina Reguladora de Trámites",
lee las fechas con cupo (campo oculto #fechas_disponibles) y avisa por Telegram.
NUNCA reserva ni pulsa "Siguiente": solo mira, avisa y deja el calendario listo.

La ventana (app.py) lo lanza como proceso aparte y lee su registro. Los datos
(config, perfil de Chrome, sesión, log) van en la carpeta VIGILANTE_DATA.

Roles: el PC "principal" avisa siempre y deja una señal de vida en el bot
(descripción corta en zulú, invisible para la gente). El PC "respaldo" solo
avisa de cupos cuando esa señal tiene más de LATIDO_MAX segundos.
"""
import ctypes
import datetime as dt
import json
import logging
import os
import random
import re
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import winsound
except ImportError:  # Linux
    winsound = None

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ES_WINDOWS = os.name == "nt"
BASE = Path(os.environ.get("VIGILANTE_DATA") or Path(__file__).resolve().parent)
CONFIG = BASE / "config.json"
MANIFEST = BASE / "manifest.json"  # copia del manifest del servidor (ajustes remotos)
PERFIL = BASE / "perfil_chrome"
RESPUESTAS = BASE / "respuestas"
SESION = BASE / "sesion.json"
REGISTRO = BASE / "vigilante.log"

MEC = "https://bpmgob.mec.gub.uy"
BANDEJA = MEC + "/etapas/inbox"
IDIOMA_LATIDO = "zu"
LATIDO_CADA = 60
LATIDO_MAX = 150

log = logging.info


def configurar_log():
    handlers = [logging.FileHandler(REGISTRO, encoding="utf-8")]
    if sys.stdout and not getattr(sys, "frozen", False):  # en la app empaquetada no hay consola
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S", handlers=handlers)


class SesionCaida(Exception):
    pass


class VentanaCerrada(Exception):
    pass


def comprobar_ventana(page):
    if page.is_closed():
        raise VentanaCerrada()


def cargar_config():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    # Ajustes que el administrador cambia para todos desde el servidor.
    try:
        cfg.update(json.loads(MANIFEST.read_text(encoding="utf-8")).get("ajustes", {}))
    except Exception:
        pass
    # Formato antiguo: telegram_chat_id + telegram_chat_ids_extra.
    if "chats_avisos" not in cfg and cfg.get("telegram_chat_id"):
        cfg["chats_avisos"] = [cfg["telegram_chat_id"]] + list(cfg.get("telegram_chat_ids_extra", []))
    cfg.setdefault("chats_avisos", [])
    cfg.setdefault("chat_dueno", (cfg["chats_avisos"] or [""])[0])
    cfg.setdefault("rol", "principal")
    cfg.setdefault("url_agenda", "")
    cfg.setdefault("texto_ubicacion", "Oficina Reguladora")
    cfg.setdefault("meses_a_vigilar", 5)
    cfg.setdefault("intervalo_segundos", 60)
    cfg.setdefault("latido_horas", 6)
    cfg.setdefault("recordatorio_minutos", 5)
    cfg.setdefault("intervalo_rapido_segundos", 5)
    cfg.setdefault("congelar_minutos", 3)
    cfg["intervalo_segundos"] = max(30, int(cfg["intervalo_segundos"]))
    cfg["intervalo_rapido_segundos"] = max(3, float(cfg["intervalo_rapido_segundos"]))
    return cfg


def guardar_url_agenda(url):
    """Guarda en la config el trámite encontrado (sin pisar el resto de cambios)."""
    try:
        c = json.loads(CONFIG.read_text(encoding="utf-8"))
        c["url_agenda"] = url
        CONFIG.write_text(json.dumps(c, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as e:
        log(f"No pude guardar el trámite en la config: {error_corto(e)}")


def error_corto(e):
    # Los errores de Playwright pueden incluir cabeceras con cookies: solo la primera línea.
    return str(e).splitlines()[0][:200] if str(e) else type(e).__name__


# ---------------------------------------------------------------- Telegram

def telegram(cfg, metodo, datos=None):
    url = f"https://api.telegram.org/bot{cfg['telegram_token']}/{metodo}"
    body = urllib.parse.urlencode(datos).encode() if datos else None
    with urllib.request.urlopen(url, data=body, timeout=20) as r:
        return json.loads(r.read().decode())


def enviar(cfg, destinos, texto):
    if not cfg.get("telegram_token") or not destinos:
        log("(Telegram sin configurar) " + texto)
        return False
    enviados = 0
    for chat in destinos:
        for intento in range(3):
            try:
                telegram(cfg, "sendMessage", {"chat_id": chat, "text": texto,
                                              "disable_web_page_preview": "true"})
                enviados += 1
                break
            except Exception as e:
                log(f"Fallo enviando Telegram a {chat} (intento {intento + 1}): {error_corto(e)}")
                time.sleep(2)
    return enviados > 0


def avisar(cfg, texto):
    """Mensajes del sistema (activado, sesión, problemas): solo al dueño de este PC."""
    return enviar(cfg, [str(cfg["chat_dueno"])] if cfg.get("chat_dueno") else [], texto)


_latido = {"leido": 0.0, "vivo": False, "escrito": 0.0}


def principal_vivo(cfg):
    """True si el PC principal dejó su señal de vida hace poco (se consulta como mucho cada 20 s)."""
    if time.time() - _latido["leido"] < 20:
        return _latido["vivo"]
    try:
        r = telegram(cfg, "getMyShortDescription", {"language_code": IDIOMA_LATIDO})
        m = re.search(r"vivo (\d+)", r.get("result", {}).get("short_description", ""))
        _latido["vivo"] = bool(m) and time.time() - int(m.group(1)) < LATIDO_MAX
    except Exception as e:
        log(f"No pude leer la señal del PC principal: {error_corto(e)}")
        _latido["vivo"] = False  # ante la duda, avisar
    _latido["leido"] = time.time()
    return _latido["vivo"]


def dejar_latido(cfg):
    """El principal deja 'vivo <hora>' en el bot, en segundo plano para no frenar la vigilancia."""
    if cfg["rol"] != "principal" or not cfg.get("telegram_token"):
        return
    if time.time() - _latido["escrito"] < LATIDO_CADA:
        return
    _latido["escrito"] = time.time()

    def tarea():
        try:
            telegram(cfg, "setMyShortDescription",
                     {"short_description": f"vivo {int(time.time())}", "language_code": IDIOMA_LATIDO})
        except Exception as e:
            log(f"No pude dejar la señal de vida: {error_corto(e)}")
    threading.Thread(target=tarea, daemon=True).start()


def avisar_cupo(cfg, texto):
    """Avisos de cupos: a todos, salvo que este PC sea el respaldo y el principal esté vivo."""
    if cfg["rol"] == "respaldo" and principal_vivo(cfg):
        log("Cupo detectado; avisa el PC principal (está activo).")
        return False
    return enviar(cfg, [str(c) for c in cfg["chats_avisos"]], texto)


# ---------------------------------------------------------------- Agenda

def meses_ventana(n):
    hoy = dt.date.today()
    meses = []
    for i in range(n):
        m = hoy.month - 1 + i
        meses.append((hoy.year + m // 12, m % 12 + 1))
    return meses


def revisar(page, cfg):
    """Devuelve (fechas_con_cupo_en_ventana, posible_cupo_visual, api, cuerpo)."""
    if not cfg["url_agenda"]:
        raise SesionCaida("todavía no hay trámite en Agenda")
    page.goto(cfg["url_agenda"], wait_until="domcontentloaded", timeout=60000)
    if "/etapas/ejecutar/" not in page.url:
        raise SesionCaida(page.url)

    try:
        page.wait_for_selector("input[type=radio]", timeout=30000)
    except PWTimeout:
        raise SesionCaida("no aparece la opción de ubicación")

    with page.expect_response(lambda r: "agenda_sae_api_disponibilidades" in r.url, timeout=45000) as resp_info:
        ok = page.evaluate(
            """(texto) => {
                const r = [...document.querySelectorAll('input[type=radio]')]
                    .find(x => (x.parentElement.textContent || '').includes(texto));
                if (!r) return false;
                r.checked = false;
                r.click();
                return true;
            }""",
            cfg["texto_ubicacion"],
        )
        if not ok:
            raise SesionCaida("no encontré la opción '%s'" % cfg["texto_ubicacion"])
    resp = resp_info.value
    if resp.status != 200:
        raise RuntimeError(f"la API de disponibilidades respondió {resp.status}")
    cuerpo = resp.text()

    page.wait_for_selector(".ui-datepicker-inline", timeout=20000)
    page.wait_for_timeout(1500)

    valor = page.evaluate("() => (document.getElementById('fechas_disponibles') || {}).value || ''")
    sin_cupos_visible = page.evaluate(
        """() => [...document.querySelectorAll('div,span,p,strong')]
              .some(e => /No hay cupos disponibles/i.test(e.textContent) && e.offsetParent !== null)"""
    )
    # Respaldo visual: recorre los meses en el calendario contando días verdes (seleccionables).
    dias_verdes = 0
    for i in range(cfg["meses_a_vigilar"]):
        dias_verdes += page.evaluate(
            """() => [...document.querySelectorAll('.ui-datepicker-inline td')]
                  .filter(td => !td.classList.contains('ui-datepicker-unselectable') && td.textContent.trim()).length"""
        )
        if i < cfg["meses_a_vigilar"] - 1:
            page.evaluate("() => document.querySelector('.ui-datepicker-inline .ui-datepicker-next')?.click()")
            page.wait_for_timeout(400)

    ventana = set(meses_ventana(cfg["meses_a_vigilar"]))
    fechas = sorted(
        {f"{d}/{m}/{a}" for d, m, a in re.findall(r"(\d{2})/(\d{2})/(\d{4})", valor) if (int(a), int(m)) in ventana},
        key=lambda s: (s[6:], s[3:5], s[:2]),
    )

    if valor or fechas or dias_verdes or not sin_cupos_visible:
        # Guarda la respuesta cruda por si el formato cambia y hay que ajustar el código.
        RESPUESTAS.mkdir(exist_ok=True)
        (RESPUESTAS / dt.datetime.now().strftime("%Y%m%d_%H%M%S.txt")).write_text(
            f"fechas_disponibles={valor}\ndias_verdes={dias_verdes}\nsin_cupos_visible={sin_cupos_visible}\n\n{cuerpo}",
            encoding="utf-8",
        )

    posible_visual = bool(dias_verdes) or not sin_cupos_visible
    # Guarda cómo pidió el sitio la disponibilidad para repetirla en los sondeos rápidos.
    req = resp.request
    api = {
        "url": resp.url,
        "post": req.post_data,
        "headers": {k: v for k, v in req.headers.items()
                    if k.lower() in ("content-type", "x-requested-with", "accept")},
    }
    return fechas, posible_visual, api, cuerpo


def sondeo_rapido(page, api):
    """Repite solo la petición de disponibilidad (ligera) desde la propia página, con su sesión y TLS."""
    comprobar_ventana(page)
    res = page.evaluate(
        """async (api) => {
            const ctrl = new AbortController();
            const t = setTimeout(() => ctrl.abort(), 15000);
            try {
                const r = await fetch(api.url, {method: 'POST', body: api.post, headers: api.headers,
                                                credentials: 'same-origin', redirect: 'manual', signal: ctrl.signal});
                return {status: r.status, texto: await r.text()};
            } finally { clearTimeout(t); }
        }""",
        api,
    )
    if res["status"] != 200:
        raise RuntimeError(f"el sondeo rápido respondió {res['status']}")
    return res["texto"]


def huella(cuerpo):
    """Horarios con cupo en la respuesta de la API ({"20261228": {"11:00": {"cupo": 1}}})."""
    try:
        datos = json.loads(cuerpo)
        horarios = set()
        for dia in datos.get("disponibilidades") or []:
            for fecha, horas in dia.items():
                for hora, info in (horas or {}).items():
                    if isinstance(info, dict) and int(info.get("cupo") or 0) > 0:
                        horarios.add(f"{fecha} {hora}")
        return horarios
    except Exception:
        return set(re.findall(r"\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}|\b20\d{6}\b", cuerpo))


def en_agenda(page, cfg):
    """True si la página muestra la opción de ubicación (sesión iniciada y en la etapa Agenda)."""
    comprobar_ventana(page)
    try:
        return page.evaluate(
            """(texto) => [...document.querySelectorAll('input[type=radio]')]
                  .some(x => (x.parentElement.textContent || '').includes(texto))""",
            cfg["texto_ubicacion"],
        )
    except Exception:
        return False


def sesion_iniciada(page):
    """True si la ventana está en el MEC con la sesión abierta (no en el login de ID Uruguay)."""
    comprobar_ventana(page)
    if not page.url.startswith(MEC):
        return False
    try:
        return not page.evaluate(
            """() => /Uso de la aplicación no permitida/i.test(document.body.innerText)
                  || !!document.querySelector('a[href*="autenticacion/login"]')"""
        )
    except Exception:
        return False


def buscar_agenda(page, cfg):
    """Abre la bandeja y prueba cada trámite hasta dar con uno que esté en el paso Agenda."""
    page.goto(BANDEJA, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    ids = []
    for href in page.evaluate("() => [...document.querySelectorAll('a[href]')].map(a => a.href)"):
        m = re.search(r"/etapas/ejecutar/(\d+)", href)
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    for tramite in ids[:15]:
        for url in (f"{MEC}/etapas/ejecutar/{tramite}/1", f"{MEC}/etapas/ejecutar/{tramite}"):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2500)
            except Exception:
                continue
            if en_agenda(page, cfg):
                return page.url.split("?")[0].split("#")[0]
    return None


def esperar_login(page, cfg):
    """Espera a que la persona inicie sesión y a que haya un trámite en Agenda (lo busca solo)."""
    try:
        page.goto(cfg["url_agenda"] or BANDEJA, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
    except Exception as e:
        log(f"No pude abrir el MEC: {error_corto(e)}")
    if en_agenda(page, cfg):
        log("Sesión OK.")
        return
    log("Esperando a que inicies sesión en la ventana de Chrome del vigilante...")
    ultima_url, ultimo_cambio, ultima_busqueda, avisado = page.url, time.time(), 0.0, False
    while True:
        # No recarga mientras la persona escribe o navega; solo comprueba cada 5 s.
        time.sleep(5)
        if en_agenda(page, cfg):
            url = page.url.split("?")[0].split("#")[0]
            if url != cfg["url_agenda"]:
                cfg["url_agenda"] = url
                guardar_url_agenda(url)
                log(f"Trámite en Agenda: {url}")
            log("Sesión OK.")
            return
        if page.url != ultima_url:
            ultima_url, ultimo_cambio = page.url, time.time()
        quieto = time.time() - ultimo_cambio > 60
        if quieto and time.time() - ultima_busqueda > 90 and sesion_iniciada(page):
            ultima_busqueda = time.time()
            log("Sesión iniciada: busco un trámite que esté en la Agenda...")
            url = buscar_agenda(page, cfg)
            if url:
                cfg["url_agenda"] = url
                guardar_url_agenda(url)
                log(f"Trámite en Agenda encontrado: {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2000)
            else:
                log("No encontré ningún trámite en la Agenda. Abre uno nuevo hasta el paso Agenda.")
                if not avisado:
                    avisar(cfg, "📋 No encontré ningún trámite en la Agenda del MEC. Abre uno nuevo hasta el paso "
                                "Agenda en la ventana del vigilante y sigo solo.")
                    avisado = True
            ultima_url, ultimo_cambio = page.url, time.time()


# ---------------------------------------------------------------- Modo reserva

MARCA_TITULO = "¡CUPO MEC!"


def mostrar_primer_cupo(page, cfg):
    """Deja el calendario en el primer mes que tenga días verdes (revisar() lo dejó en el último)."""
    n = cfg["meses_a_vigilar"]
    for _ in range(n - 1):
        page.evaluate("() => document.querySelector('.ui-datepicker-inline .ui-datepicker-prev')?.click()")
        page.wait_for_timeout(250)
    for _ in range(n - 1):
        verdes = page.evaluate(
            """() => [...document.querySelectorAll('.ui-datepicker-inline td')]
                  .some(td => !td.classList.contains('ui-datepicker-unselectable') && td.textContent.trim())"""
        )
        if verdes:
            break
        page.evaluate("() => document.querySelector('.ui-datepicker-inline .ui-datepicker-next')?.click()")
        page.wait_for_timeout(250)


def traer_al_frente(page):
    """Restaura/maximiza la ventana de Chrome del vigilante y la pone delante de todo."""
    try:
        page.bring_to_front()
        cdp = page.context.new_cdp_session(page)
        wid = cdp.send("Browser.getWindowForTarget")["windowId"]
        cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
        cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "maximized"}})
        cdp.detach()
    except Exception as e:
        log(f"No pude maximizar la ventana: {error_corto(e)}")
    try:
        page.evaluate("(m) => { if (!document.title.startsWith(m)) document.title = m + ' ' + document.title; }",
                      MARCA_TITULO)
        page.wait_for_timeout(500)
        if not ES_WINDOWS:
            return  # en Linux basta con lo que hace Chrome (maximizar y activar la pestaña)
        user32 = ctypes.windll.user32
        ventanas = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def buscar(hwnd, _):
            largo = user32.GetWindowTextLengthW(hwnd)
            if largo:
                buf = ctypes.create_unicode_buffer(largo + 1)
                user32.GetWindowTextW(hwnd, buf, largo + 1)
                if MARCA_TITULO in buf.value:
                    ventanas.append(hwnd)
            return True

        user32.EnumWindows(buscar, 0)
        for hwnd in ventanas:
            # Pulsar ALT permite que Windows deje pasar la ventana al frente.
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)
            user32.ShowWindow(hwnd, 3)
            user32.SetForegroundWindow(hwnd)
    except Exception as e:
        log(f"No pude traer la ventana al frente: {error_corto(e)}")


def modo_reserva(page, cfg, segundos):
    """No recarga ni sondea mientras dura la espera o mientras la persona usa la ventana."""
    page.evaluate(
        """() => {
            window.__act = 0;
            if (!window.__actHook) {
                window.__actHook = true;
                for (const ev of ['click', 'keydown', 'mousemove', 'wheel'])
                    addEventListener(ev, () => { window.__act = Date.now(); }, true);
            }
        }"""
    )
    inicio = time.time()
    log(f"MODO RESERVA: la ventana queda quieta {segundos // 60 or segundos}"
        f"{' min' if segundos >= 60 else ' s'} (más si la estás usando).")
    while True:
        comprobar_ventana(page)
        time.sleep(2)
        try:
            url = page.url
            inactivo = page.evaluate("() => window.__act ? (Date.now() - window.__act) / 1000 : 1e9")
        except Exception:
            url, inactivo = "", 1e9  # navegando entre páginas
        usando = url.split("#")[0] != cfg["url_agenda"] or inactivo < 60
        transcurrido = time.time() - inicio
        if transcurrido >= 20 * 60 or (transcurrido >= segundos and not usando):
            break
    log("Fin del modo reserva, sigo vigilando.")


# ---------------------------------------------------------------- Bucle

def alarma_local():
    for _ in range(5):
        if winsound:
            winsound.Beep(1500, 400)
        elif sys.stdout:
            print("\a", end="", flush=True)
        time.sleep(0.15)


def abrir_chrome(p, headless=False):
    opciones = dict(headless=headless, no_viewport=True)
    try:
        return p.chromium.launch_persistent_context(str(PERFIL), channel="chrome", **opciones)
    except Exception as e:
        primero = error_corto(e)
    # Linux sin Google Chrome: Chromium del sistema (no el de snap, que no puede usar esta carpeta)...
    for nombre in ("chromium", "chromium-browser", "google-chrome-stable"):
        ruta = shutil.which(nombre)
        if ruta and "/snap/" not in os.path.realpath(ruta):
            log(f"No encontré Google Chrome; uso {ruta}")
            return p.chromium.launch_persistent_context(str(PERFIL), executable_path=ruta, **opciones)
    # ...o el Chromium que bajó el instalador (PLAYWRIGHT_BROWSERS_PATH).
    try:
        ctx = p.chromium.launch_persistent_context(str(PERFIL), **opciones)
        log("Uso el Chromium incluido en la app.")
        return ctx
    except Exception as e:
        raise RuntimeError(f"No hay navegador: instala Google Chrome ({primero} / {error_corto(e)})")


def main():
    configurar_log()
    cfg = cargar_config()
    simulacro = "--simulacro" in sys.argv
    prueba = "--prueba" in sys.argv or simulacro

    if ES_WINDOWS:
        # Evita que Windows se suspenda mientras el vigilante corre.
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)

    with sync_playwright() as p:
        ctx = abrir_chrome(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        # Chrome descarta las cookies de sesión al cerrarse; las restauramos de la última vez.
        if SESION.exists():
            try:
                ctx.add_cookies(json.loads(SESION.read_text(encoding="utf-8")).get("cookies", []))
            except Exception as e:
                log(f"No pude restaurar la sesión guardada: {error_corto(e)}")

        esperar_login(page, cfg)
        avisar(cfg, "✅ Bot activado")
        log(f"Rol de este PC: {cfg['rol']}.")

        ultimo_latido = time.time()
        ultimo_aviso_cupo = 0.0
        ultimas_fechas = []
        fallos = 0
        ultimo_aviso_fallo = 0.0
        revisiones = 0
        sondeos = 0
        api = None
        base = ""
        forzar_completa = True
        ultima_completa = 0.0
        ultimo_cambio = 0.0

        while True:
            try:
                ahora = time.time()
                if not (forzar_completa or api is None or ahora - ultima_completa >= cfg["intervalo_segundos"]):
                    cuerpo = sondeo_rapido(page, api)
                    sondeos += 1
                    dejar_latido(cfg)
                    if cuerpo.strip() != base.strip():
                        nuevas = huella(cuerpo) - huella(base)
                        # Horarios nuevos -> revisión completa ya; otro cambio -> como mucho cada 30 s.
                        if nuevas or ahora - ultimo_cambio > 30:
                            log("Cambió la respuesta de disponibilidad"
                                + (f" ({len(nuevas)} horario(s) nuevo(s))" if nuevas else "")
                                + " -> revisión completa")
                            ultimo_cambio = ahora
                            forzar_completa = True
                            continue
                    time.sleep(max(1.0, cfg["intervalo_rapido_segundos"] + random.uniform(-1, 1)))
                    continue

                meses_txt = ", ".join(f"{m:02d}/{a}" for a, m in meses_ventana(cfg["meses_a_vigilar"]))
                fechas, posible_visual, api, base = revisar(page, cfg)
                ctx.storage_state(path=str(SESION))
                dejar_latido(cfg)
                if simulacro:
                    # Finge un cupo mañana para probar el aviso de punta a punta.
                    fechas = [(dt.date.today() + dt.timedelta(days=1)).strftime("%d/%m/%Y") + " (SIMULACRO)"]
                forzar_completa = False
                ultima_completa = time.time()
                revisiones += 1
                fallos = 0
                ahora = time.time()

                if fechas:
                    nuevas = fechas != ultimas_fechas
                    aparecio_otra = bool(set(fechas) - set(ultimas_fechas))
                    log("CUPOS: " + ", ".join(fechas))
                    if aparecio_otra:
                        # Deja el calendario listo en la ventana del vigilante para reservar a mano.
                        try:
                            mostrar_primer_cupo(page, cfg)
                        except Exception as e:
                            log(f"No pude mover el calendario: {error_corto(e)}")
                        traer_al_frente(page)
                    if nuevas or ahora - ultimo_aviso_cupo > cfg["recordatorio_minutos"] * 60:
                        avisar_cupo(cfg, "🚨 ¡HAY CUPOS en el MEC! Fechas: " + ", ".join(fechas)
                                    + f"\nEntra ya: {MEC}")
                        ultimo_aviso_cupo = ahora
                        alarma_local()
                    ultimas_fechas = fechas
                    if aparecio_otra:
                        modo_reserva(page, cfg, 15 if simulacro else int(cfg["congelar_minutos"] * 60))
                        forzar_completa = True
                elif posible_visual:
                    if ahora - ultimo_aviso_cupo > cfg["recordatorio_minutos"] * 60:
                        avisar_cupo(cfg, f"⚠️ Posible cupo en el MEC. Revisa ya: {MEC}")
                        ultimo_aviso_cupo = ahora
                        alarma_local()
                    log("Posible cupo (señal visual)")
                else:
                    ultimas_fechas = []
                    log(f"Sin cupos ({meses_txt}). Revisión completa #{revisiones}, sondeos rápidos: {sondeos}")

                if prueba:
                    avisar(cfg, f"🧪 Prueba OK. Fechas con cupo ahora: {', '.join(fechas) or 'ninguna'}")
                    break

                if ahora - ultimo_latido > cfg["latido_horas"] * 3600:
                    avisar(cfg, f"💤 Sigo vigilando. {revisiones} revisiones completas y {sondeos} sondeos, sin cupos por ahora.")
                    ultimo_latido = ahora

            except VentanaCerrada:
                raise
            except SesionCaida as e:
                log(f"Sesión caída o trámite fuera de la Agenda: {error_corto(e)}")
                api = None
                if not sesion_iniciada(page):
                    avisar(cfg, "🔒 Se cerró la sesión del MEC. Inicia sesión otra vez en la ventana del vigilante para que siga revisando.")
                esperar_login(page, cfg)
                avisar(cfg, "✅ Sigo vigilando.")
                forzar_completa = True
                continue
            except Exception as e:
                comprobar_ventana(page)
                forzar_completa = True
                fallos += 1
                log(f"Error en revisión ({fallos} seguidos): {error_corto(e)}")
                if fallos >= 3 and time.time() - ultimo_aviso_fallo > 3600:
                    avisar(cfg, f"⚠️ El vigilante MEC tiene problemas ({fallos} fallos seguidos): {error_corto(e)[:120]}")
                    ultimo_aviso_fallo = time.time()
                if prueba:
                    break

            time.sleep(cfg["intervalo_rapido_segundos"] if api else cfg["intervalo_segundos"])

        ctx.close()


def ejecutar():
    try:
        main()
    except VentanaCerrada:
        log("Se cerró la ventana de Chrome del vigilante. Saliendo (la app lo vuelve a abrir).")
        sys.exit(1)
    except Exception as e:
        log(f"El motor se detuvo por un error: {error_corto(e)}")
        sys.exit(1)


if __name__ == "__main__":
    ejecutar()
