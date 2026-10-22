"""Genera icono.png e icono.ico (radar verde sobre fondo azul)."""
from pathlib import Path

from PIL import Image, ImageDraw

AQUI = Path(__file__).resolve().parent
T = 512
img = Image.new("RGBA", (T, T), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([16, 16, T - 16, T - 16], radius=110, fill=(30, 64, 175))
c = T // 2
for r, ancho in ((190, 22), (130, 20), (70, 18)):
    d.ellipse([c - r, c - r, c + r, c + r], outline=(255, 255, 255, 230), width=ancho)
d.pieslice([c - 190, c - 190, c + 190, c + 190], start=-90, end=-30, fill=(34, 197, 94, 200))
d.ellipse([c - 26, c - 26, c + 26, c + 26], fill=(34, 197, 94))
d.ellipse([c + 70, c - 150, c + 118, c - 102], fill=(250, 204, 21))
img.save(AQUI.parent / "codigo" / "icono.png")
img.save(AQUI / "icono.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icono listo")
