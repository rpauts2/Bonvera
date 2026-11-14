"""Генерация премиальных подложек для карточек офферов.

Картинка несёт только графику: градиент, свет, объект категории и полупрозрачный
монограммный знак. Весь текст (бренд, продукт, награда, условие) живёт в карточке
приложения — раньше он был впечатан в JPG, из-за чего дублировался и читался
неразборчиво на размере карточки.

Скрипт не зависит от конкретной ОС: шрифт ищется в типовых путях Linux и Windows.
"""
from pathlib import Path
import hashlib
import os

import yaml
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent
D = ROOT / "assets" / "offers"
W, H = 900, 520

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def font(size: int):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def mix(a, b, t):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


PALETTES = {
    "cards": ((12, 21, 48), (47, 86, 170), (30, 220, 200)),
    "bk": ((16, 12, 40), (75, 35, 150), (255, 155, 40)),
    "mfo": ((13, 27, 38), (20, 105, 100), (100, 220, 170)),
    "cpl": ((28, 16, 44), (104, 43, 130), (255, 185, 75)),
}


def background(seed: int, cat: str) -> Image.Image:
    """Мягкий тёмный градиент со свечением под знак бренда.

    Без жёстких клиньев и линий: картинка должна выглядеть дорого на любом
    размере, тем более в маленькой плитке каталога.
    """
    c1, c2, accent = PALETTES[cat]
    c1 = mix(c1, (seed >> 16 & 255, seed >> 8 & 255, seed & 255), 0.14)

    xx = np.linspace(0, 1, W, dtype=np.float32)[None, :, None]
    yy = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    t = np.clip(0.55 * xx + 0.45 * yy, 0, 1)
    base = np.array(c1, dtype=np.float32)[None, None, :] * (1 - t) + np.array(c2, dtype=np.float32)[None, None, :] * t

    gy = np.linspace(0, H - 1, H, dtype=np.float32)[:, None]
    gx = np.linspace(0, W - 1, W, dtype=np.float32)[None, :]

    def glow(cx, cy, rx, ry, color, strength):
        g = np.clip(1 - np.sqrt(((gx - cx) / rx) ** 2 + ((gy - cy) / ry) ** 2), 0, 1)
        g = (g * g)[..., None]
        return g * np.array(color, dtype=np.float32)[None, None, :] * strength

    img = base
    img = img + glow(320, 255, 330, 300, accent, 0.30)   # свечение под монограмму
    img = img + glow(640, 300, 300, 260, (255, 255, 255), 0.06)

    vignette = 1 - np.clip(((gx - 450) / 560) ** 2 + ((gy - 260) / 430) ** 2, 0, 1) * 0.38
    img = img * vignette[..., None]

    im = Image.fromarray(np.uint8(np.clip(img, 0, 255)), "RGB").convert("RGBA")

    d = ImageDraw.Draw(im, "RGBA")
    for i in range(4):
        cx = 150 + (i % 2) * 560 + (seed % 80)
        cy = 130 + (i // 2) * 300 + ((seed // 80) % 60)
        r = 96 + (i * 23) % 70
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(*accent, 14), width=2)
    return im


def monogram(im: Image.Image, letter: str, accent) -> None:
    """Полупрозрачный знак бренда — украшение, а не логотип.

    Знак стоит в левой части кадра: карточка обрезает картинку по центру
    (object-cover), и в видимую зону попадает именно он.
    """
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")
    cx, cy, r = 320, 255, 112
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(*accent, 150), width=3)
    d.ellipse((cx - r + 14, cy - r + 14, cx + r - 14, cy + r - 14), outline=(*accent, 70), width=2)
    f = font(150)
    box = d.textbbox((0, 0), letter, font=f)
    d.text((cx - (box[2] - box[0]) / 2 - box[0], cy - (box[3] - box[1]) / 2 - box[1]), letter, font=f,
           fill=(*accent, 150))
    im.alpha_composite(layer)


def category_object(im: Image.Image, cat: str, accent) -> None:
    """Объект категории в правой части кадра — тоже в зоне, которая не режется.

    Карточка обрезает картинку по центру (900 -> ~650 пикселей кадра), поэтому
    объект держим в зоне X ~ 480..730, а монограмму — в зоне X ~ 210..430.
    """
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")

    if cat == "cards":
        # Стопка стеклянных панелей — абстракция «продукт», без логотипа и реквизитов.
        for i, (dx, dy, alpha) in enumerate(((0, 30, 70), (30, 15, 95), (60, 0, 125))):
            d.rounded_rectangle((434 + dx, 156 + dy, 706 + dx, 366 + dy), radius=28,
                                fill=(12, 18, 38, alpha), outline=(*accent, 220 - i * 40), width=3)
        d.rounded_rectangle((492, 196, 592, 226), radius=9, fill=(*accent, 70))
        d.arc((580, 288, 672, 346), 180, 350, fill=(228, 236, 255, 200), width=5)
    elif cat == "bk":
        # Сфера с мячом и светящейся дугой.
        d.ellipse((482, 132, 718, 368), fill=(242, 246, 250, 240), outline=(*accent, 255), width=5)
        d.polygon([(582, 162), (627, 177), (640, 221), (602, 249), (562, 222), (560, 182)],
                  fill=(18, 23, 40, 255))
        d.polygon([(516, 242), (562, 222), (602, 249), (588, 302), (537, 307)],
                  fill=(18, 23, 40, 255))
        d.polygon([(640, 221), (687, 232), (702, 282), (660, 312), (602, 249)],
                  fill=(18, 23, 40, 255))
        d.arc((499, 147, 712, 360), 0, 360, fill=(*accent, 150), width=3)
    elif cat == "mfo":
        # Монета со знаком рубля и полосой «наличные».
        d.ellipse((512, 162, 688, 338), fill=(247, 190, 70, 245), outline=(255, 232, 145, 255), width=5)
        d.ellipse((530, 180, 670, 320), outline=(150, 110, 30, 150), width=2)
        d.text((562, 190), "₽", font=font(104), fill=(80, 50, 18, 255))
        d.rounded_rectangle((498, 352, 702, 390), radius=12, fill=(10, 40, 50, 200),
                            outline=(*accent, 200), width=3)
    else:
        # Заявка/лид: документ с отметкой.
        d.rounded_rectangle((500, 125, 700, 375), radius=20, fill=(245, 247, 255, 240),
                            outline=(*accent, 255), width=5)
        for yy in (181, 231, 281):
            d.line((540, yy, 660, yy), fill=(55, 75, 105, 170), width=7)
        d.ellipse((622, 281, 708, 367), fill=(20, 190, 135, 245), outline=(255, 255, 255, 255), width=3)
        d.line((646, 325, 664, 343), fill=(255, 255, 255, 255), width=7)
        d.line((664, 343, 692, 303), fill=(255, 255, 255, 255), width=7)

    glow = layer.filter(ImageFilter.GaussianBlur(14))
    im.alpha_composite(Image.blend(Image.new("RGBA", im.size, (0, 0, 0, 0)), glow, 0.55))
    im.alpha_composite(layer)


def make(row):
    code = row["code"]
    cat = row["category"]
    brand = row["name"]
    seed = int(hashlib.sha256(code.encode()).hexdigest()[:8], 16)
    accent = PALETTES[cat][2]

    im = background(seed, cat)
    monogram(im, (brand.strip()[:1] or "B").upper(), accent)
    category_object(im, cat, accent)

    path = D / cat / f"{code}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(path, "JPEG", quality=88, optimize=True)


def main():
    rows = yaml.safe_load((ROOT / "catalog.yaml").read_text(encoding="utf-8"))["offers"]
    for row in rows:
        make(row)
    saved = sum(1 for r in rows if (D / r["category"] / f"{r['code']}.jpg").exists())
    print("images", len(rows), "saved", saved)


if __name__ == "__main__":
    main()
