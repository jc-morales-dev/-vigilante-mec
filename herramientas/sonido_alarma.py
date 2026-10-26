"""Crea los sonidos de alarma para el celular y los manda por el bot a todos los chats.

En Telegram se guarda uno como sonido de notificación (máximo 5 s y 300 KB) y se pone en el chat del bot:
así cada aviso de cupo suena con ese sonido.

    python herramientas/sonido_alarma.py                     crea el mp3 del teléfono y lo manda
    python herramientas/sonido_alarma.py --crear             solo los crea
    python herramientas/sonido_alarma.py campana sirena      solo esos
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CARPETA = RAIZ / "herramientas" / "sonidos"
POR_DEFECTO = ("telefono",)
NOMBRES = {"despertador": "⏰ Despertador", "campana": "🔔 Campana", "telefono": "☎️ Teléfono antiguo",
           "sirena": "🚨 Sirena"}
INSTRUCCIONES = (
    "Para que cada aviso de cupo suene con uno de estos sonidos:\n"
    "1. Escúchalos y mantén pulsado el que te guste → «Guardar para notificaciones».\n"
    "2. Toca el nombre del bot arriba → Notificaciones → Sonido → elígelo.\n"
    "3. En el celular: Ajustes → Apps → Telegram → Notificaciones: sonido activado y que pueda "
    "sonar con «No molestar».\n"
    "4. Sube el volumen de notificaciones."
)


def crear(tipos):
    spec = importlib.util.spec_from_file_location("motor", RAIZ / "codigo" / "motor.py")
    motor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(motor)
    ffmpeg = shutil.which("ffmpeg") or sys.exit("Falta ffmpeg para crear los mp3.")
    CARPETA.mkdir(exist_ok=True)
    archivos = []
    with tempfile.TemporaryDirectory() as tmp:
        for tipo in tipos:
            wav = Path(tmp) / f"{tipo}.wav"
            mp3 = CARPETA / f"alarma_{tipo}.mp3"
            wav.write_bytes(motor.sonido_alarma(segundos=4.8, tipo=tipo))
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(wav), "-codec:a", "libmp3lame",
                            "-b:a", "128k", "-metadata", f"title=alarma_{tipo}", str(mp3)], check=True)
            print(f"Creado {mp3.name} ({mp3.stat().st_size // 1024} KB)")
            archivos.append((tipo, mp3))
    return archivos


def config_bot():
    for config in sorted((RAIZ / "privado").glob("config_*.json")):
        cfg = json.loads(config.read_text(encoding="utf-8"))
        if cfg.get("telegram_token"):
            return cfg
    sys.exit("No encontré el token del bot en privado/config_*.json.")


def pedir(cfg, metodo, campos, archivo=None):
    limite = uuid.uuid4().hex
    cuerpo = b"".join(f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8")
                      for k, v in campos.items())
    if archivo:
        cuerpo += (f'--{limite}\r\nContent-Disposition: form-data; name="audio"; filename="{archivo.name}"\r\n'
                   f'Content-Type: audio/mpeg\r\n\r\n'.encode() + archivo.read_bytes() + b"\r\n")
    cuerpo += f"--{limite}--\r\n".encode()
    pedido = urllib.request.Request(f"https://api.telegram.org/bot{cfg['telegram_token']}/{metodo}", data=cuerpo,
                                    headers={"Content-Type": f"multipart/form-data; boundary={limite}"})
    with urllib.request.urlopen(pedido, timeout=60) as r:
        return json.loads(r.read().decode()).get("ok")


def mandar(archivos):
    cfg = config_bot()
    for chat in cfg.get("chats_avisos", []):
        try:
            for tipo, mp3 in archivos:
                pedir(cfg, "sendAudio", {"chat_id": chat, "caption": NOMBRES.get(tipo, tipo),
                                         "title": f"alarma_{tipo}"}, mp3)
            pedir(cfg, "sendMessage", {"chat_id": chat, "text": INSTRUCCIONES})
            print(f"Chat {chat}: enviados {len(archivos)} sonidos")
        except Exception as e:
            print(f"Chat {chat}: no se pudo enviar ({str(e).splitlines()[0][:100]})")


if __name__ == "__main__":
    tipos = [a for a in sys.argv[1:] if not a.startswith("--")] or list(POR_DEFECTO)
    archivos = crear(tipos)
    if "--crear" not in sys.argv:
        mandar(archivos)
