"""Crea el sonido de alarma para el celular y lo manda por el bot a todos los chats.

En Telegram se guarda como sonido de notificación (máximo 5 s y 300 KB) y se pone en el chat del bot:
así cada aviso de cupo suena como una sirena.

    python herramientas/sonido_alarma.py           crea herramientas/alarma_mec.mp3 y lo manda
    python herramientas/sonido_alarma.py --crear   solo lo crea
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
MP3 = RAIZ / "herramientas" / "alarma_mec.mp3"
INSTRUCCIONES = (
    "🔔 Sonido de alarma para los avisos de cupo del MEC.\n\n"
    "Para que cada aviso suene así:\n"
    "1. Mantén pulsado este audio → «Guardar para notificaciones».\n"
    "2. Toca el nombre del bot arriba → Notificaciones → Sonido → elige «alarma_mec».\n"
    "3. En el celular: Ajustes → Apps → Telegram → Notificaciones: sonido activado y que pueda "
    "sonar con «No molestar».\n"
    "4. Sube el volumen de notificaciones."
)


def crear():
    spec = importlib.util.spec_from_file_location("motor", RAIZ / "codigo" / "motor.py")
    motor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(motor)
    ffmpeg = shutil.which("ffmpeg") or sys.exit("Falta ffmpeg para crear el mp3.")
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "alarma.wav"
        wav.write_bytes(motor.sonido_alarma(segundos=4.8))
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(wav), "-codec:a", "libmp3lame",
                        "-b:a", "128k", "-metadata", "title=alarma_mec", str(MP3)], check=True)
    print(f"Creado {MP3.name} ({MP3.stat().st_size // 1024} KB)")


def mandar():
    config = next((c for c in sorted((RAIZ / "privado").glob("config_*.json"))
                   if json.loads(c.read_text(encoding="utf-8")).get("telegram_token")), None)
    if not config:
        sys.exit("No encontré el token del bot en privado/config_*.json.")
    cfg = json.loads(config.read_text(encoding="utf-8"))
    for chat in cfg.get("chats_avisos", []):
        limite = uuid.uuid4().hex
        partes = []
        for nombre, valor in (("chat_id", str(chat)), ("caption", INSTRUCCIONES), ("title", "alarma_mec")):
            partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{nombre}"\r\n\r\n{valor}\r\n'
                          .encode("utf-8"))
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="audio"; filename="alarma_mec.mp3"'
                      f'\r\nContent-Type: audio/mpeg\r\n\r\n'.encode() + MP3.read_bytes() + b"\r\n")
        partes.append(f"--{limite}--\r\n".encode())
        pedido = urllib.request.Request(f"https://api.telegram.org/bot{cfg['telegram_token']}/sendAudio",
                                        data=b"".join(partes),
                                        headers={"Content-Type": f"multipart/form-data; boundary={limite}"})
        try:
            with urllib.request.urlopen(pedido, timeout=60) as r:
                ok = json.loads(r.read().decode()).get("ok")
            print(f"Chat {chat}: {'enviado' if ok else 'Telegram no lo aceptó'}")
        except Exception as e:
            print(f"Chat {chat}: no se pudo enviar ({str(e).splitlines()[0][:100]})")


if __name__ == "__main__":
    crear()
    if "--crear" not in sys.argv:
        mandar()
