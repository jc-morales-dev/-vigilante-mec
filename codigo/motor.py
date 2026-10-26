"""
Vigilante de cupos - MEC Inscripción de partidas extranjeras (motor).

Recarga la etapa "Agenda" del trámite, marca "Oficina Reguladora de Trámites",
lee las fechas con cupo (campo oculto #fechas_disponibles) y avisa por Telegram.
NUNCA reserva ni pulsa "Siguiente": solo mira, avisa y deja el calendario listo.

La ventana (app.py) lo lanza como proceso aparte y lee su registro. Los datos
(config, perfil de Chrome, sesión, log) van en la carpeta VIGILANTE_DATA.

Quién avisa: cada PC deja una señal de vida en el bot (descripción corta en un
idioma por rol, invisible para la gente). El ajuste "avisa" del servidor elige
el equipo que manda los avisos de cupos ("Victor", "Jose", "todos" o vacío =
el principal); los demás solo avisan si la señal de ese equipo tiene más de
LATIDO_MAX segundos o dice que no está vigilando.
"""
import ctypes
import datetime as dt
import json
import logging
import math
import os
import random
import re
import shutil
import subprocess
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
# Una "ranura" del bot por rol para la señal de vida (la del principal es la de siempre).
IDIOMAS_LATIDO = {"principal": "zu", "respaldo": "xh"}
LATIDO_CADA = 60
LATIDO_MAX = 150
try:
    VERSION = (Path(__file__).resolve().parent / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    VERSION = "?"

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
    # Ajustes que el administrador cambia desde el servidor: "ajustes" para todos y
    # "equipos" -> {"Jose": {...}} solo para un equipo (gana sobre los de todos).
    try:
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cfg.update(man.get("ajustes") or {})
        propios = {k.lower(): v for k, v in (man.get("equipos") or {}).items()}
        cfg.update(propios.get(str(cfg.get("nombre", "")).lower()) or {})
    except Exception:
        pass
    # Formato antiguo: telegram_chat_id + telegram_chat_ids_extra.
    if "chats_avisos" not in cfg and cfg.get("telegram_chat_id"):
        cfg["chats_avisos"] = [cfg["telegram_chat_id"]] + list(cfg.get("telegram_chat_ids_extra", []))
    cfg.setdefault("chats_avisos", [])
    cfg.setdefault("chat_dueno", (cfg["chats_avisos"] or [""])[0])
    cfg.setdefault("rol", "principal")
    cfg["nombre"] = re.sub(r"\s+", "_", str(cfg.get("nombre") or cfg["rol"]).strip())
    cfg.setdefault("avisa", "")
    cfg.setdefault("avisos_sistema", "todos")
    cfg.setdefault("telegram_activo", True)
    cfg.setdefault("url_agenda", "")
    cfg.setdefault("texto_ubicacion", "Oficina Reguladora")
    cfg.setdefault("meses_a_vigilar", 5)
    cfg.setdefault("intervalo_segundos", 60)
    cfg.setdefault("latido_horas", 6)
    cfg.setdefault("recordatorio_minutos", 5)
    cfg.setdefault("intervalo_rapido_segundos", 5)
    cfg.setdefault("congelar_minutos", 3)
    # Ráfaga de mensajes al aparecer un cupo: cada uno hace sonar el celular.
    cfg.setdefault("alarma_repeticiones", 6)
    cfg.setdefault("alarma_cada_segundos", 5)
    cfg.setdefault("chats_alarma", cfg["chats_avisos"])
    cfg["intervalo_segundos"] = max(30, int(cfg["intervalo_segundos"]))
    cfg["intervalo_rapido_segundos"] = max(3, float(cfg["intervalo_rapido_segundos"]))
    cfg["alarma_repeticiones"] = max(0, min(20, int(cfg["alarma_repeticiones"])))
    cfg["alarma_cada_segundos"] = max(3, float(cfg["alarma_cada_segundos"]))
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
    if not cfg["telegram_activo"]:
        log("(Telegram desactivado en este equipo) " + texto)
        return False
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
    """Mensajes del sistema (activado, sesión, problemas), con el nombre del equipo.

    Con avisos_sistema "todos" (por defecto) les llegan a todos los chats; con "dueno", solo al dueño de este PC.
    """
    dueno = [str(cfg["chat_dueno"])] if cfg.get("chat_dueno") else []
    if cfg["avisos_sistema"] == "dueno":
        destinos = dueno
    else:
        destinos = list(dict.fromkeys([str(c) for c in cfg["chats_avisos"]] + dueno))
    return enviar(cfg, destinos, f"[PC de {cfg['nombre']}] {texto}")


_latido = {"leido": 0.0, "equipos": [], "escrito": 0.0, "estado": ""}


def interpretar_latido(texto, rol):
    """'vigilando 1761400000 Jose respaldo 1.2.0' -> dict (acepta el antiguo 'vivo 1761400000')."""
    p = texto.split()
    if len(p) < 2 or not p[1].isdigit():
        return None
    return {"estado": "vigilando" if p[0] == "vivo" else p[0], "hora": int(p[1]),
            "nombre": p[2] if len(p) > 2 else "", "rol": p[3] if len(p) > 3 else rol,
            "version": p[4] if len(p) > 4 else ""}


def leer_latidos(cfg):
    """Señales de vida de todos los equipos (se consultan como mucho cada 20 s)."""
    if time.time() - _latido["leido"] < 20:
        return _latido["equipos"]
    equipos = []
    for rol, idioma in IDIOMAS_LATIDO.items():
        try:
            r = telegram(cfg, "getMyShortDescription", {"language_code": idioma})
        except Exception as e:
            log(f"No pude leer la señal de los otros equipos: {error_corto(e)}")
            continue  # ante la duda, ese equipo cuenta como apagado y este avisa
        latido = interpretar_latido(r.get("result", {}).get("short_description", ""), rol)
        if latido:
            equipos.append(latido)
    _latido.update(leido=time.time(), equipos=equipos)
    return equipos


def soy_quien_avisa(cfg):
    avisa = str(cfg["avisa"]).strip().lower()
    if avisa in ("", "auto"):
        return cfg["rol"] == "principal"
    return avisa in ("todos", cfg["nombre"].lower())


def avisa_otro_equipo(cfg):
    """Nombre del equipo elegido para avisar si no es este y está vigilando ahora; si no, None."""
    avisa = str(cfg["avisa"]).strip().lower()
    for l in leer_latidos(cfg):
        elegido = l["rol"] == "principal" if avisa in ("", "auto") else l["nombre"].lower() == avisa
        if (elegido and l["nombre"].lower() != cfg["nombre"].lower() and l["estado"] == "vigilando"
                and time.time() - l["hora"] < LATIDO_MAX):
            return l["nombre"] or l["rol"]
    return None


def dejar_latido(cfg, estado="vigilando"):
    """Deja '<estado> <hora> <nombre> <rol> <versión>' en el bot, en segundo plano para no frenar.

    Estados: vigilando, esperando (sin sesión del MEC) o mudo (Telegram desactivado en este PC);
    con cualquiera que no sea vigilando, los otros equipos avisan enseguida.
    """
    if not cfg.get("telegram_token"):
        return
    if not cfg["telegram_activo"]:
        estado = "mudo"
    if estado == _latido["estado"] and time.time() - _latido["escrito"] < LATIDO_CADA:
        return
    _latido.update(escrito=time.time(), estado=estado)
    texto = f"{estado} {int(time.time())} {cfg['nombre']} {cfg['rol']} {VERSION}"
    idioma = IDIOMAS_LATIDO.get(cfg["rol"], IDIOMAS_LATIDO["principal"])

    def tarea():
        try:
            telegram(cfg, "setMyShortDescription", {"short_description": texto, "language_code": idioma})
        except Exception as e:
            log(f"No pude dejar la señal de vida: {error_corto(e)}")
    threading.Thread(target=tarea, daemon=True).start()


def alarma_telegram(cfg, destinos, veces=None, prueba=False):
    """Ráfaga de mensajes de alarma, uno cada alarma_cada_segundos, en segundo plano."""
    veces = cfg["alarma_repeticiones"] if veces is None else veces
    if not veces or not destinos:
        return

    def tarea():
        for i in range(1, veces + 1):
            time.sleep(cfg["alarma_cada_segundos"])
            enviar(cfg, destinos, f"🧪 PRUEBA de alarma {i}/{veces}" if prueba
                   else f"🚨🔔 ALARMA {i}/{veces}: ¡HAY CUPO EN EL MEC! Entra ya: {MEC}")
    threading.Thread(target=tarea, daemon=True).start()


def avisar_cupo(cfg, texto, alarma=False):
    """Avisos de cupos: a todos, salvo que otro equipo sea el elegido para avisar y esté vigilando.

    Con alarma (cupo nuevo) sigue una ráfaga de mensajes a chats_alarma.
    """
    if not soy_quien_avisa(cfg):
        otro = avisa_otro_equipo(cfg)
        if otro:
            log(f"Cupo detectado; avisa el PC de {otro} (está vigilando).")
            return False
    enviado = enviar(cfg, [str(c) for c in cfg["chats_avisos"]], f"{texto}\n(avisa el PC de {cfg['nombre']})")
    if enviado and alarma:
        alarma_telegram(cfg, [str(c) for c in cfg["chats_alarma"]])
    return enviado


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
        fuera = page.evaluate(
            """() => /Uso de la aplicación no permitida/i.test(document.body.innerText) ? 'no permitida'
                  : document.querySelector('a[href*="autenticacion/login"]') ? 'enlace de login' : ''"""
        )
    except Exception as e:
        fuera = error_corto(e)
    if fuera:
        log(f"Sin sesión del MEC ({fuera}).")
    return not fuera


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
    ultimo_estado = 0.0
    while True:
        dejar_latido(cfg, "esperando")
        if time.time() - ultimo_estado > 300:
            ultimo_estado = time.time()
            log(f"Esperando sesión/trámite (la ventana está en {page.url.split('?')[0]})")
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
        dejar_latido(cfg)  # sigue al mando: el cupo ya se avisó desde aquí
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

def sonido_alarma(segundos=3.0, muestreo=22050):
    """WAV de sirena de dos tonos (900/1400 Hz), con el volumen al máximo.

    Sin el módulo struct: no viene en la app instalada.
    """
    def n(valor, largo):
        return int(valor).to_bytes(largo, "little")

    muestras = bytearray()
    fase = 0.0
    for i in range(int(segundos * muestreo)):
        tono = 1400 if (i / muestreo * 3) % 1 < 0.5 else 900
        fase += 2 * math.pi * tono / muestreo
        valor = max(-1.0, min(1.0, 1.6 * math.sin(fase)))  # algo recortada: suena más fuerte
        muestras += int(valor * 32000).to_bytes(2, "little", signed=True)
    cabecera = (b"RIFF" + n(36 + len(muestras), 4) + b"WAVEfmt " + n(16, 4) + n(1, 2) + n(1, 2)
                + n(muestreo, 4) + n(muestreo * 2, 4) + n(2, 2) + n(16, 2) + b"data" + n(len(muestras), 4))
    return cabecera + bytes(muestras)


def alarma_local(veces=4):
    """Hace sonar la sirena en este PC, en segundo plano para no frenar la vigilancia."""
    def tarea():
        try:
            sonido = sonido_alarma()
            if winsound:
                for _ in range(veces):
                    winsound.PlaySound(sonido, winsound.SND_MEMORY)
                return
            archivo = BASE / "alarma.wav"
            archivo.write_bytes(sonido)
            reproductor = next((r for r in ("paplay", "pw-play", "aplay") if shutil.which(r)), None)
            if not reproductor:
                log("No puedo hacer sonar la alarma en este equipo (falta paplay o aplay).")
                return
            for _ in range(veces):
                subprocess.run([reproductor, str(archivo)], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30)
        except Exception as e:
            log(f"No pude hacer sonar la alarma: {error_corto(e)}")
    threading.Thread(target=tarea, daemon=True).start()


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


def impedir_suspension():
    """Evita que el equipo se suspenda mientras el vigilante corre."""
    if ES_WINDOWS:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
        return
    if not shutil.which("systemd-inhibit"):
        log("No puedo impedir que el equipo se suspenda (falta systemd-inhibit): desactiva la suspensión.")
        return
    try:
        # El bloqueo dura lo que viva este proceso (tail --pid termina cuando el motor se cierra).
        subprocess.Popen(["systemd-inhibit", "--what=sleep:idle", "--who=Vigilante MEC",
                          "--why=Vigilando los cupos del MEC", "--mode=block",
                          "tail", f"--pid={os.getpid()}", "-f", "/dev/null"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("Suspensión del equipo bloqueada mientras vigilo.")
    except Exception as e:
        log(f"No pude impedir que el equipo se suspenda: {error_corto(e)}")


def recargar_config(cfg):
    """Vuelve a leer la config y los ajustes del servidor (la app baja el manifest cada pocos minutos)."""
    try:
        nuevo = cargar_config()
    except Exception as e:
        log(f"No pude releer la config: {error_corto(e)}")
        return cfg
    cambios = sorted(k for k in set(cfg) | set(nuevo) if cfg.get(k) != nuevo.get(k))
    if cambios:
        log("Ajustes nuevos: " + ", ".join(cambios))
    return nuevo


def main():
    configurar_log()
    cfg = cargar_config()
    simulacro = "--simulacro" in sys.argv
    prueba = "--prueba" in sys.argv or simulacro
    log(f"Vigilante v{VERSION} en el PC de {cfg['nombre']} ({cfg['rol']}).")
    impedir_suspension()

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
        log(f"Rol de este PC: {cfg['rol']}."
            + ("" if cfg["telegram_activo"] else " Telegram desactivado en este equipo: avisa el otro PC."))
        dejar_latido(cfg)

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

                cfg = recargar_config(cfg)
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
                                    + f"\nEntra ya: {MEC}", alarma=aparecio_otra)
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
