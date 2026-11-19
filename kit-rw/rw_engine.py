#!/usr/bin/env python3
"""Moteur de rendu Réveil Watt — format « tes droits et ton argent ».

Usage :
  python3 rw_engine.py words  main_words.json                 -> liste les mots avec leur temps
  python3 rw_engine.py check  scenes.json main_words.json     -> résout les ancres "at" et affiche le plan
  python3 rw_engine.py stills scenes.json main.mp3 main_words.json planche.jpg
  python3 rw_engine.py render scenes.json main.mp3 main_words.json sortie.mp4
  python3 rw_engine.py thumb  scenes.json miniature.jpg
Tout est dessiné en code (fond, cartes, personnage, sous-titres, bruitages discrets).
"""
import json, math, random, re, subprocess, sys, unicodedata, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1080, 1920, 30
F_BLACK = "/usr/share/fonts/opentype/inter/Inter-Black.otf"
F_XB = "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf"
F_SB = "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf"
F_MONO = "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"
F_JP = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"
F_EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
F_FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_fc = {}
def font(p, s):
    k = (p, s)
    if k not in _fc:
        try: _fc[k] = ImageFont.truetype(p, s)
        except OSError: _fc[k] = ImageFont.truetype(F_FALLBACK, s)
    return _fc[k]

YEL = (255, 210, 63); RED = (255, 77, 94); WHITE = (255, 255, 255); GREEN = (60, 220, 130)
CARD = (27, 35, 80); CARD_B = (52, 64, 128); PAPER = (244, 239, 226); INK = (40, 40, 52); NAVY = (40, 50, 104)
COLORS = {"red": RED, "yellow": YEL, "green": (46, 160, 96), "navy": NAVY, "white": WHITE}

# ---------- easing ----------
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def ease_out(t): t = clamp(t); return 1 - (1 - t) ** 3
def ease_in_out(t): t = clamp(t); return 3 * t * t - 2 * t * t * t
def back(t):
    t = clamp(t); c1 = 1.70158; c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2
def pop(t, t0, d=0.35):
    if t < t0: return 0.0, 0.0
    k = (t - t0) / d
    return 0.6 + 0.4 * back(k), clamp(k * 2.5)
def window(t, t0, t1, fin=0.25):
    if t < t0 or t > t1 + fin: return 0.0
    return 1 - (t - t1) / fin if t > t1 else 1.0

# ---------- primitives ----------
def rrect_img(w, h, fill, r=34, border=None, shadow=True):
    pad = 40 if shadow else 0
    img = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([pad, pad + 14, pad + w, pad + h + 14], r, fill=(0, 0, 0, 130))
        img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(18)))
    ImageDraw.Draw(img).rounded_rectangle([pad, pad, pad + w, pad + h], r, fill=fill, outline=border, width=3 if border else 0)
    hl = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(hl).rounded_rectangle([pad + 3, pad + 3, pad + w - 3, pad + h * 0.45], r - 4, fill=(255, 255, 255, 10))
    return Image.alpha_composite(img, hl)

def paste(base, img, cx, cy, scale=1.0, alpha=1.0):
    if alpha <= 0.01 or scale <= 0.01: return
    if abs(scale - 1) > 0.01:
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.BILINEAR)
    if alpha < 0.99:
        img = img.copy(); img.putalpha(img.getchannel("A").point(lambda v: int(v * alpha)))
    x, y = int(cx - img.width / 2), int(cy - img.height / 2)
    sx, sy = max(0, -x), max(0, -y); ex, ey = min(img.width, W - x), min(img.height, H - y)
    if ex <= sx or ey <= sy: return
    if (sx, sy, ex, ey) != (0, 0, img.width, img.height): img = img.crop((sx, sy, ex, ey))
    base.alpha_composite(img, (x + sx, y + sy))

def text_img(txt, f, fill, stroke=0, sfill=(0, 0, 0)):
    b = f.getbbox(txt, stroke_width=stroke)
    img = Image.new("RGBA", (b[2] - b[0] + 8, b[3] - b[1] + 8), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((4 - b[0], 4 - b[1]), txt, font=f, fill=fill, stroke_width=stroke, stroke_fill=sfill)
    return img

def pill(txt, bg, fg=WHITE, size=34):
    t = text_img(txt, font(F_XB, size), fg)
    w, h = t.width + 44, t.height + 22
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, w - 1, h - 1], h // 2, fill=bg)
    img.alpha_composite(t, ((w - t.width) // 2, (h - t.height) // 2))
    return img

def big_amount(txt, col, size=150):
    t = text_img(txt, font(F_BLACK, size), col)
    g = Image.new("RGBA", (t.width + 60, t.height + 60), (0, 0, 0, 0)); g.alpha_composite(t, (30, 30))
    out = Image.new("RGBA", g.size, (0, 0, 0, 0)); out.alpha_composite(g.filter(ImageFilter.GaussianBlur(18))); out.alpha_composite(g)
    return out

def wrap(d, txt, f, maxw):
    lines, cur = [], ""
    for w in txt.split():
        test = (cur + " " + w).strip()
        if d.textlength(test, font=f) <= maxw: cur = test
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines

def col(name, default=RED): return COLORS.get(name, default) if isinstance(name, str) else tuple(name)

# ---------- fond ----------
def make_bg():
    rnd = random.Random(7)
    y = np.linspace(0, 1, H)[:, None]
    top = np.array([13, 20, 62]); bot = np.array([6, 9, 32])
    g = np.zeros((H, W, 3), np.float32)
    for c in range(3): g[:, :, c] = top[c] * (1 - y) + bot[c] * y
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.sqrt(((xx - W / 2) / W) ** 2 + ((yy - 760) / H) ** 2)
    g += (np.clip(1 - d * 2.2, 0, 1) ** 2)[:, :, None] * np.array([18, 26, 70])
    img = Image.fromarray(np.clip(g, 0, 255).astype(np.uint8)).convert("RGBA")
    dr = ImageDraw.Draw(img)
    for _ in range(140):
        x, yv = rnd.randint(0, W), rnd.randint(0, H)
        dr.ellipse([x, yv, x + 2, yv + 2], fill=(255, 255, 255, rnd.randint(20, 70)))
    return img

GLYPHS = "01ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄ7392"
def make_rain():
    rnd = random.Random(8); cols = []; f = font(F_JP, 30)
    for _ in range(16):
        strip = Image.new("RGBA", (40, H * 2), (0, 0, 0, 0)); d = ImageDraw.Draw(strip)
        for j in range(0, H * 2, 38):
            if rnd.random() < 0.55: d.text((4, j), rnd.choice(GLYPHS), font=f, fill=(70, 230, 140, rnd.randint(10, 38)))
        cols.append((strip, rnd.randint(30, W - 50), rnd.uniform(40, 110), rnd.randint(0, H)))
    return cols

# ---------- personnage (original, 2 variantes) ----------
def _radial(size, c_in, c_out, cx=0.4, cy=0.35):
    w, h = size; yy, xx = np.mgrid[0:h, 0:w]
    d = np.clip(np.sqrt((xx / w - cx) ** 2 + (yy / h - cy) ** 2) / 0.75, 0, 1)[:, :, None]
    return Image.fromarray((np.array(c_in) * (1 - d) + np.array(c_out) * d).astype(np.uint8)).convert("RGBA")
def _shaped(size, draw, c_in, c_out, cx=0.4, cy=0.3):
    m = Image.new("L", size, 0); draw(ImageDraw.Draw(m)); g = _radial(size, c_in, c_out, cx, cy); g.putalpha(m); return g

def character(pose, fem=False):
    S = 3; w, h = 300 * S, 520 * S; cx = w // 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([cx - 95 * S, 492 * S, cx + 95 * S, 515 * S], fill=(0, 0, 0, 120))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6 * S)))
    img.alpha_composite(_shaped((w, h), lambda d: (d.rounded_rectangle([cx - 52 * S, 360 * S, cx - 8 * S, 495 * S], 18 * S, fill=255),
                                                   d.rounded_rectangle([cx + 8 * S, 360 * S, cx + 52 * S, 495 * S], 18 * S, fill=255)),
                                (55, 66, 98), (24, 28, 44), 0.35, 0.75))
    img.alpha_composite(_shaped((w, h), lambda d: (d.rounded_rectangle([cx - 62 * S, 478 * S, cx - 2 * S, 505 * S], 12 * S, fill=255),
                                                   d.rounded_rectangle([cx + 2 * S, 478 * S, cx + 62 * S, 505 * S], 12 * S, fill=255)),
                                (250, 250, 250), (170, 175, 190), 0.4, 0.92))
    def arm(d, p0, p1, p2):
        d.line([p0, p1, p2], fill=255, width=34 * S, joint="curve")
        for p in (p0, p1, p2): d.ellipse([p[0] - 17 * S, p[1] - 17 * S, p[0] + 17 * S, p[1] + 17 * S], fill=255)
    L0, R0 = (cx - 78 * S, 230 * S), (cx + 78 * S, 230 * S)
    down_l = (L0, (cx - 100 * S, 300 * S), (cx - 92 * S, 365 * S)); down_r = (R0, (cx + 100 * S, 300 * S), (cx + 92 * S, 365 * S))
    la, ra = {"point": (down_l, (R0, (cx + 140 * S, 170 * S), (cx + 175 * S, 105 * S))),
              "shock": ((L0, (cx - 135 * S, 175 * S), (cx - 110 * S, 95 * S)), (R0, (cx + 135 * S, 175 * S), (cx + 110 * S, 95 * S))),
              "think": (down_l, (R0, (cx + 70 * S, 300 * S), (cx + 30 * S, 190 * S)))}.get(pose, (down_l, down_r))
    hair = (58, 34, 26) if fem else (34, 26, 24)
    if fem:
        d0 = ImageDraw.Draw(img)
        d0.rounded_rectangle([cx - 86 * S, 70 * S, cx - 56 * S, 250 * S], 14 * S, fill=hair)
        d0.rounded_rectangle([cx + 56 * S, 70 * S, cx + 86 * S, 250 * S], 14 * S, fill=hair)
    img.alpha_composite(_shaped((w, h), lambda d: d.rounded_rectangle([cx - 95 * S, 205 * S, cx + 95 * S, 380 * S], 48 * S, fill=255),
                                (64, 68, 88), (20, 22, 32), 0.35, 0.3))
    dd = ImageDraw.Draw(img)
    dd.line([cx, 215 * S, cx, 375 * S], fill=(12, 14, 22), width=3 * S)
    dd.rounded_rectangle([cx - 60 * S, 315 * S, cx + 60 * S, 360 * S], 14 * S, outline=(14, 16, 24), width=3 * S)
    dd.text((cx - 55 * S, 240 * S), "01", font=font(F_MONO, 26 * S), fill=(70, 230, 140))
    img.alpha_composite(_shaped((w, h), lambda d: (arm(d, *la), arm(d, *ra)), (70, 74, 92), (22, 24, 34), 0.5, 0.3))
    dd = ImageDraw.Draw(img)
    for p in (la[2], ra[2]):
        dd.ellipse([p[0] - 19 * S, p[1] - 19 * S, p[0] + 19 * S, p[1] + 19 * S], fill=(233, 178, 140))
        dd.ellipse([p[0] - 12 * S, p[1] - 14 * S, p[0] + 2 * S, p[1] - 2 * S], fill=(248, 205, 172))
    if not fem: dd.ellipse([cx - 92 * S, 60 * S, cx + 92 * S, 235 * S], fill=(30, 33, 46))
    img.alpha_composite(_shaped((w, h), lambda d: d.ellipse([cx - 72 * S, 52 * S, cx + 72 * S, 212 * S], fill=255),
                                (252, 208, 176), (196, 136, 104), 0.4, 0.3))
    dd = ImageDraw.Draw(img)
    dd.chord([cx - 76 * S, 40 * S, cx + 76 * S, 170 * S], 180, 360, fill=hair)
    dd.ellipse([cx - 40 * S, 34 * S, cx + 30 * S, 80 * S], fill=(74, 44, 34) if fem else (46, 36, 32))
    if not fem:
        for sx in (-1, 1): dd.ellipse([cx + sx * 74 * S - 12 * S, 120 * S, cx + sx * 74 * S + 12 * S, 152 * S], fill=(222, 160, 126))
    for sx in (-1, 1):
        ex = cx + sx * 32 * S
        dd.ellipse([ex - 28 * S, 112 * S, ex + 28 * S, 150 * S], fill=(10, 12, 18))
        dd.ellipse([ex - 18 * S, 118 * S, ex - 4 * S, 128 * S], fill=(90, 220, 150, 200))
    dd.line([cx - 6 * S, 126 * S, cx + 6 * S, 126 * S], fill=(10, 12, 18), width=5 * S)
    if pose == "shock":
        dd.ellipse([cx - 14 * S, 168 * S, cx + 14 * S, 196 * S], fill=(90, 30, 40)); dd.ellipse([cx - 8 * S, 182 * S, cx + 8 * S, 194 * S], fill=(220, 90, 100))
    elif pose == "think": dd.line([cx - 14 * S, 182 * S, cx + 16 * S, 176 * S], fill=(110, 50, 50), width=5 * S)
    else: dd.arc([cx - 24 * S, 150 * S, cx + 24 * S, 190 * S], 20, 160, fill=(110, 50, 50), width=5 * S)
    if fem: dd.rounded_rectangle([cx - 42 * S, 200 * S, cx + 42 * S, 222 * S], 10 * S, fill=(232, 92, 120))
    return img.resize((w // S, h // S), Image.LANCZOS)

# ---------- mots, nombres, ancres ----------
def norm(s):
    s = unicodedata.normalize("NFD", s.lower()); s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9'\-]", "", s.replace("’", "'"))

def load_words(path):
    d = json.load(open(path)); ws = d["words"] if isinstance(d, dict) else d
    return [w for w in ws if w.get("type", "word") == "word" and norm(w["text"])]

UNITS = {"zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
         "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20, "vingts": 20, "trente": 30,
         "quarante": 40, "cinquante": 50, "soixante": 60, "et": None}
def parse_fr_number(tokens):
    """tokens: list of normalized words (may contain hyphens). Returns int or None."""
    parts = []
    for t in tokens: parts += [p for p in t.split("-") if p]
    if not parts or any(p not in UNITS and p not in ("cent", "cents", "mille", "million", "millions") for p in parts): return None
    if all(p == "et" for p in parts): return None
    total, cur = 0, 0
    i = 0
    while i < len(parts):
        p = parts[i]
        if p == "et": i += 1; continue
        if p in ("cent", "cents"): cur = (cur or 1) * 100
        elif p == "mille": total += (cur or 1) * 1000; cur = 0
        elif p in ("million", "millions"): total += (cur or 1) * 1_000_000; cur = 0
        elif p == "quatre" and i + 1 < len(parts) and parts[i + 1] in ("vingt", "vingts"): cur += 80; i += 1
        elif p in ("vingt", "vingts") and cur % 100 == 0 and i > 0 and parts[i - 1] == "quatre": cur += 80
        elif UNITS[p] >= 10 and cur % 100 in (60, 80) and UNITS[p] < 20: cur += UNITS[p]
        else: cur += UNITS[p]
        i += 1
    return total + cur

def fmt_num(n): return f"{n:,}".replace(",", " ")

def number_span(words, i):
    """longest run of number words starting at i -> (value, j_end_exclusive)"""
    best = None
    first = norm(words[i]["text"])
    if first == "et": return None
    if first in ("un", "une"):
        nxt = norm(words[i + 1]["text"]) if i + 1 < len(words) else ""
        if nxt not in ("euro", "euros", "mille", "million", "millions"): return None
    for j in range(i + 1, min(len(words), i + 8) + 1):
        toks = [norm(w["text"]) for w in words[i:j]]
        if toks[-1] == "et": continue
        v = parse_fr_number(toks)
        if v is None: break
        best = (v, j)
    return best

def resolve(at, words, start_idx=0):
    """'at' -> (time, index). number = seconds ; string = phrase searched from start_idx."""
    if isinstance(at, (int, float)):
        idx = next((k for k, w in enumerate(words) if w["start"] >= at), len(words) - 1)
        return float(at), idx
    target = [norm(x) for x in at.split()]
    for rng in (range(start_idx, len(words)), range(0, len(words))):
        for k in rng:
            if [norm(w["text"]) for w in words[k:k + len(target)]] == target:
                return words[k]["start"], k
    raise ValueError(f"Ancre introuvable dans la voix : « {at} »")

# ---------- sous-titres ----------
STOP = {"à", "le", "la", "les", "de", "du", "des", "que", "dans", "tu", "ce", "sa", "ta", "ton", "tes", "ses", "et", "en", "un", "une",
        "au", "par", "pour", "plus", "ne", "si", "qu'un", "on", "te", "lui", "c'est", "pas", "ça", "qu'on", "son", "sur", "ou", "qui", "il", "elle"}
def build_captions(words, red, yellow):
    red = {norm(x) for x in red}; yellow = {norm(x) for x in yellow}
    toks = []; i = 0
    while i < len(words):
        sp = number_span(words, i)
        if sp:
            v, j = sp
            euro = j < len(words) and norm(words[j]["text"]) in ("euros", "euro")
            disp = "*" + fmt_num(v) + (" €" if euro else "") + "*"
            jj = j + (1 if euro else 0)
            toks.append((words[i]["start"], words[jj - 1]["end"], disp, True)); i = jj; continue
        t = words[i]["text"]; n = norm(t)
        disp = ("#" if n in red else "*" if n in yellow else "") + t.upper().strip(".,;:!?…«»\"")
        toks.append((words[i]["start"], words[i]["end"], disp, False)); i += 1
    caps, cur = [], []
    for tk in toks:
        if cur:
            gap = tk[0] - cur[-1][1]; length = sum(len(x[2]) for x in cur)
            if len(cur) >= 3 or gap > 0.22 or length + len(tk[2]) > 18 or tk[3]:
                carry = []
                while gap <= 0.22 and len(cur) > 1 and norm(cur[-1][2].strip("*#")) in STOP and len(carry) < 2:
                    carry.insert(0, cur.pop())
                caps.append((cur[0][0], " ".join(x[2] for x in cur))); cur = carry
        cur.append(tk)
        if tk[3] and len(cur) == 1 + 0: pass
    if cur: caps.append((cur[0][0], " ".join(x[2] for x in cur)))
    return caps

def caption_img(txt):
    f = font(F_BLACK, 66); parts = []
    for tok in txt.split(" "):
        c = YEL if tok.startswith("*") else RED if tok.startswith("#") else WHITE
        parts.append((tok.strip("*#"), c))
    imgs = [text_img(p, f, c) for p, c in parts if p]
    if not imgs: return Image.new("RGBA", (1, 1))
    sp = 22; tw = sum(i.width for i in imgs) + sp * (len(imgs) - 1); hh = max(i.height for i in imgs)
    scale = min(1.0, 980 / max(1, tw + 40))
    img = Image.new("RGBA", (tw + 40, hh + 40), (0, 0, 0, 0)); x = 20
    for i in imgs: img.alpha_composite(i, (x, 20 + hh - i.height)); x += i.width + sp
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0)); sh.putalpha(img.getchannel("A").filter(ImageFilter.GaussianBlur(10)).point(lambda v: v * 0.8))
    out = Image.new("RGBA", img.size, (0, 0, 0, 0)); out.alpha_composite(sh, (0, 6)); out.alpha_composite(img)
    if scale < 1: out = out.resize((int(out.width * scale), int(out.height * scale)), Image.LANCZOS)
    return out

# ---------- éléments ----------
def make_street():
    w, h = 1000, 520; img = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(img); R = random.Random(11); x = 0
    while x < w:
        bw = R.randint(90, 150); bh = R.randint(200, 360)
        d.rectangle([x, h - 140 - bh, x + bw, h - 140], fill=R.choice([(52, 40, 78), (70, 46, 64), (44, 52, 90), (84, 52, 58)]))
        for wy in range(h - 120 - bh, h - 160, 34):
            for wx in range(x + 12, x + bw - 20, 28):
                if R.random() < 0.55: d.rectangle([wx, wy, wx + 14, wy + 18], fill=(255, 196, 92) if R.random() < 0.7 else (90, 96, 140))
        x += bw + R.randint(0, 6)
    d.rectangle([0, h - 140, w, h - 110], fill=(150, 150, 170)); d.rectangle([0, h - 110, w, h], fill=(70, 76, 104))
    for cx in (140, 820):
        d.ellipse([cx - 70, h - 330, cx + 70, h - 190], fill=(180, 92, 46)); d.rectangle([cx - 8, h - 200, cx + 8, h - 140], fill=(80, 50, 40))
    for cx in (420, 700):
        for k in range(4): d.ellipse([cx + k * 34 - 40, 20 + (k % 2) * 14, cx + k * 34 + 30, 80 + (k % 2) * 14], fill=(236, 238, 248))
    m = Image.new("L", (w, h), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, w, h], 30, fill=255)
    img.putalpha(Image.fromarray(np.minimum(np.array(img.getchannel("A")), np.array(m))))
    return img

def make_office():
    w, h = 1000, 520; img = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w, h], 30, fill=(38, 46, 92))
    for k in range(3):
        x0 = 80 + k * 300; d.rounded_rectangle([x0, 60, x0 + 200, 240], 12, fill=(70, 96, 170)); d.line([x0 + 100, 60, x0 + 100, 240], fill=(38, 46, 92), width=6)
    d.rectangle([0, 380, w, h], fill=(60, 50, 70)); d.rounded_rectangle([300, 300, 760, 400], 14, fill=(150, 110, 80))
    d.rounded_rectangle([600, 230, 720, 300], 8, fill=(30, 30, 40))
    return img

def make_envelope():
    img = Image.new("RGBA", (520, 340), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    d.rounded_rectangle([10, 10, 510, 330], 22, fill=(250, 246, 236), outline=(210, 200, 180), width=4)
    d.line([10, 14, 260, 190, 510, 14], fill=(210, 200, 180), width=5)
    return img

def make_stamp(txt, c, size=64, rot=-10):
    t = text_img(txt, font(F_BLACK, size), c); w, h = t.width + 44, t.height + 34
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([3, 3, w - 4, h - 4], 12, outline=c, width=7)
    img.alpha_composite(t, ((w - t.width) // 2, (h - t.height) // 2))
    return img.rotate(rot, expand=True, resample=Image.BICUBIC)

class Video:
    def __init__(self, cfg, words, dur):
        self.cfg, self.words, self.dur = cfg, words, dur
        self.BG, self.RAIN = make_bg(), make_rain()
        fem = cfg.get("perso", "f") == "f"
        self.POSE = {p: character(p, fem) for p in ("idle", "point", "shock", "think")}
        self.STREET, self.OFFICE, self.ENV = make_street(), make_office(), make_envelope()
        self.caps = [(t, caption_img(s)) for t, s in build_captions(words, cfg.get("red_words", []), cfg.get("yellow_words", []))]
        self._cache = {}
        # résolution des scènes
        self.scenes = []; idx = 0
        for sc in cfg["scenes"]:
            t0, idx = resolve(sc.get("at", 0.0), words, idx)
            if not self.scenes: t0 = 0.0
            els = []
            for el in sc.get("elements", []):
                e = dict(el)
                e["_t"], _ = resolve(el.get("at", t0), words, idx) if "at" in el else (t0, idx)
                for key in ("until", "stamp_at", "fly_at", "pill_at", "value_at", "right_at", "button_at", "result_at", "hit_at"):
                    if key in el: e["_" + key], _ = resolve(el[key], words, idx)
                for sub in ("lines", "rows", "highlight", "messages"):
                    if sub in el and isinstance(el[sub], list):
                        nl = []
                        for it in el[sub]:
                            if isinstance(it, dict) and "at" in it:
                                it = dict(it); it["_t"], _ = resolve(it["at"], words, idx)
                            nl.append(it)
                        e[sub] = nl
                els.append(e)
            poses = []
            for p in sc.get("poses", []):
                pt, _ = resolve(p["at"], words, idx); poses.append((pt, p["pose"]))
            self.scenes.append({"t0": t0, "els": els, "char": sc.get("char", {"pose": "idle", "x": 230}), "poses": poses, "name": sc.get("name", "")})
        for i, s in enumerate(self.scenes):
            s["t1"] = self.scenes[i + 1]["t0"] - 0.15 if i + 1 < len(self.scenes) else dur
        self.stamps = [e["_t"] for s in self.scenes for e in s["els"] if e["type"] in ("stamp", "hit")] + \
                      [e["_stamp_at"] for s in self.scenes for e in s["els"] if e["type"] == "envelope" and "_stamp_at" in e]

    def cached(self, key, fn):
        if key not in self._cache: self._cache[key] = fn()
        return self._cache[key]

    # --- dessin d'un élément ---
    def draw_el(self, fr, e, t, al, dx, dy):
        ty = e["type"]; t0 = e["_t"]
        if t < t0: return
        s, a = pop(t, t0)
        y = e.get("y")
        if ty == "pill":
            img = self.cached(("pill", e["text"], e.get("color")), lambda: pill(e["text"], col(e.get("color", "red")),
                              (20, 20, 30) if e.get("color") == "yellow" else WHITE, size=e.get("size", 38)))
            paste(fr, img, e.get("x", 540), y or 280, s, a * al)
        elif ty == "bigvalue":
            v = e["text"]
            if "count" in e:
                k = ease_out((t - t0) / e.get("count_dur", 0.8)); v = fmt_num(int(round(e["count"] * k))) + e.get("suffix", " €")
            paste(fr, big_amount(v, col(e.get("color", "red")), e.get("size", 150)), e.get("x", 540) + dx, (y or 300) + dy, s, a * al)
        elif ty == "hit":  # gros montant qui tombe avec secousse
            k = clamp((t - t0) / 0.18)
            paste(fr, big_amount(e["text"], col(e.get("color", "red")), e.get("size", 170)), e.get("x", 540) + dx, (y or 1000) + dy,
                  1.0 + 0.8 * (1 - ease_out(k)), al * clamp(k * 3))
        elif ty == "stamp":
            k = clamp((t - t0) / 0.18)
            img = self.cached(("stamp", e["text"]), lambda: make_stamp(e["text"], col(e.get("color", "red")), e.get("size", 70)))
            paste(fr, img, e.get("x", 540) + dx, (y or 330) + dy, 1.0 + 0.8 * (1 - ease_out(k)), al * clamp(k * 3))
        elif ty in ("street", "office"):
            paste(fr, self.STREET if ty == "street" else self.OFFICE, 540, y or 1020, 1, al * clamp((t - t0) / 0.3))
        elif ty == "valuecard":
            c = rrect_img(640, 360, CARD, border=CARD_B); d = ImageDraw.Draw(c); p = 40
            d.text((p + 44, p + 40), e.get("label", ""), font=font(F_XB, 38), fill=(170, 180, 230))
            d.text((p + 44, p + 96), e.get("sub", ""), font=font(F_SB, 34), fill=WHITE)
            v = e["value"]
            if "count" in e: v = fmt_num(int(round(e["count"] * ease_out((t - t0) / 0.45)))) + e.get("suffix", " €")
            c.alpha_composite(text_img(v, font(F_BLACK, 130), col(e.get("color", "yellow"))), (p + 44, p + 150))
            paste(fr, c, e.get("x", 540) + dx, (y or 620) + dy, s, a * al)
        elif ty == "phone":
            c = rrect_img(560, 760, (246, 247, 252), r=48); d = ImageDraw.Draw(c); p = 40
            d.rounded_rectangle([p + 200, p + 18, p + 360, p + 36], 9, fill=(20, 22, 30))
            d.text((p + 40, p + 70), e.get("title", ""), font=font(F_XB, 38), fill=(30, 34, 60))
            d.text((p + 40, p + 120), e.get("sub", ""), font=font(F_SB, 28), fill=(120, 124, 150))
            rows = e.get("rows", []); step = e.get("step", 0.22)
            for i, r in enumerate(rows[:7]):
                k = clamp((t - t0 - i * step) / 0.25)
                if k <= 0: continue
                yy = p + 180 + i * 62
                d.rounded_rectangle([p + 30, yy, p + 520, yy + 50], 14, fill=(255, 236, 238) if k >= 1 else (240, 240, 246))
                d.text((p + 50, yy + 10), r[0][:26], font=font(F_SB, 24), fill=(60, 62, 84))
                d.text((p + 505 - font(F_XB, 28).getlength(r[1]), yy + 8), r[1], font=font(F_XB, 28), fill=RED)
            if "total" in e:
                d.line([p + 30, p + 630, p + 520, p + 630], fill=(210, 212, 225), width=3)
                d.text((p + 40, p + 650), e.get("total_label", "Total"), font=font(F_XB, 34), fill=(30, 34, 60))
                tv = e["total"]
                if "total_count" in e:
                    tv = e.get("total_prefix", "-") + fmt_num(int(e["total_count"] * clamp((t - t0) / (len(rows[:7]) * step + 0.25)))) + " €"
                d.text((p + 520 - font(F_BLACK, 44).getlength(tv), p + 644), tv, font=font(F_BLACK, 44), fill=RED)
            fade = 1 - clamp((t - e["_until"] + 0.25) / 0.25) if "_until" in e else 1
            k = ease_out((t - t0) / 0.4)
            paste(fr, c, e.get("x", 640), (y or 760) + (1 - k) * 300, e.get("scale", 0.62), al * clamp(k * 2) * fade)
        elif ty == "bubble":
            msgs = e.get("messages", [])
            cur = None
            for m in msgs:
                if t >= m.get("_t", t0): cur = m["text"]
            c = rrect_img(640, 220, (245, 246, 252), r=40); d = ImageDraw.Draw(c)
            d.text((90, 88), e.get("who", ""), font=font(F_SB, 30), fill=(120, 124, 150))
            txt = cur or "…"; sz = 40
            while font(F_BLACK, sz).getlength(txt) > 520 and sz > 24: sz -= 2
            d.text((90, 134), txt, font=font(F_BLACK, sz), fill=(30, 34, 60))
            fade = 1 - 0.6 * clamp((t - e["_until"]) / 0.3) if "_until" in e else 1
            paste(fr, c, e.get("x", 600), y or 650, s, a * al * fade)
        elif ty == "gauge":
            k = ease_out((t - t0) / 0.6)
            g = Image.new("RGBA", (760, 420), (0, 0, 0, 0)); gd = ImageDraw.Draw(g)
            gd.text((20, 0), e.get("label", "PLAFOND LÉGAL"), font=font(F_XB, 34), fill=YEL)
            gd.line([0, 70, 760, 70], fill=YEL, width=8)
            gd.rounded_rectangle([300, 400 - min(int(330 * k), 330), 460, 400], 18, fill=RED)
            paste(fr, g, e.get("x", 600), y or 980, 1, al)
        elif ty == "document":
            c = rrect_img(800, 560, PAPER, r=22); d = ImageDraw.Draw(c); p = 40
            d.text((p + 44, p + 40), e.get("small", ""), font=font(F_SB, 30), fill=(110, 106, 96))
            ts = 56
            while font(F_BLACK, ts).getlength(e.get("title", "")) > 700 and ts > 30: ts -= 2
            d.text((p + 44, p + 84), e.get("title", ""), font=font(F_BLACK, ts), fill=INK)
            d.line([p + 44, p + 160, p + 756, p + 160], fill=(200, 194, 180), width=3)
            f = font(F_SB, 40); lines = [l if isinstance(l, str) else l["text"] for l in e.get("lines", [])][:5]
            for hl in e.get("highlight", []):
                li = hl["line"]; k = clamp((t - hl.get("_t", t0)) / 0.35)
                if k > 0 and li < len(lines):
                    w1 = f.getlength(lines[li])
                    d.rectangle([p + 40, p + 190 + li * 62 - 4, p + 44 + w1 * k + 6, p + 190 + li * 62 + 48], fill=(255, 216, 90))
            for i, line in enumerate(lines):
                k = clamp((t - t0 - 0.1 - i * 0.3) / 0.35)
                d.text((p + 44, p + 190 + i * 62), line[:int(len(line) * k)], font=f, fill=INK)
            paste(fr, c, e.get("x", 540), y or 720, s, a * al)
        elif ty == "toggle":
            on = ease_out((t - e.get("_value_at", t0 + 0.6)) / 0.3)
            c = rrect_img(600, 120, CARD, r=30, border=CARD_B); d = ImageDraw.Draw(c); p = 40
            d.text((p + 34, p + 34), e.get("label", ""), font=font(F_XB, 36), fill=WHITE)
            x0, y0 = p + 330, p + 30
            cc = tuple(int(a_ * (1 - on) + b_ * on) for a_, b_ in zip((70, 78, 120), GREEN))
            d.rounded_rectangle([x0, y0, x0 + 96, y0 + 56], 28, fill=cc)
            kx = x0 + 28 + on * 40; d.ellipse([kx - 22, y0 + 6, kx + 22, y0 + 50], fill=WHITE)
            if on >= 1 and e.get("value"): d.text((p + 445, p + 32), e["value"], font=font(F_BLACK, 42), fill=YEL)
            paste(fr, c, e.get("x", 490), y or 1110, s, a * al)
        elif ty == "calc":
            c = rrect_img(760, 520, CARD, border=CARD_B); d = ImageDraw.Draw(c); p = 40
            d.text((p + 50, p + 40), e.get("title", ""), font=font(F_XB, 40), fill=WHITE)
            for i, r in enumerate(e.get("rows", [])[:2]):
                rt = r.get("_t", t0 + i * 0.5)
                if t < rt: continue
                yy = p + 120 + i * 90
                d.rounded_rectangle([p + 40, yy, p + 720, yy + 70], 18, fill=NAVY)
                d.text((p + 70, yy + 16), r["label"], font=font(F_SB, 34), fill=(200, 206, 240))
                d.text((p + 690 - font(F_BLACK, 40).getlength(r["value"]), yy + 12), r["value"], font=font(F_BLACK, 40),
                       fill=col(r.get("color", "white"), WHITE))
            rs = e.get("result")
            if rs and t >= e.get("_result_at", 1e9):
                k = clamp((t - e["_result_at"]) / 0.4)
                d.line([p + 40, p + 320, p + 720, p + 320], fill=(90, 100, 170), width=3)
                d.text((p + 70, p + 350), rs["label"], font=font(F_XB, 38), fill=WHITE)
                v = fmt_num(int(round(rs.get("count", 0) * ease_out(k)))) + rs.get("suffix", " €") if "count" in rs else rs["value"]
                d.text((p + 690 - font(F_BLACK, 70).getlength(v), p + 336), v, font=font(F_BLACK, 70), fill=YEL)
            paste(fr, c, e.get("x", 470), y or 740, s, a * al)
        elif ty == "letter":
            c = rrect_img(760, 720, PAPER, r=18); d = ImageDraw.Draw(c); p = 40
            d.text((p + 44, p + 40), e.get("object", "Objet :"), font=font(F_XB, 32), fill=INK)
            d.line([p + 44, p + 92, p + 716, p + 92], fill=(200, 194, 180), width=3)
            f = font(F_SB, 38); L = e.get("lines", [])
            for i, it in enumerate(L[:7]):
                lt = it.get("_t", t0 + i); nt = L[i + 1].get("_t", lt + 1.2) if i + 1 < len(L) else lt + 1.0
                k = clamp((t - lt) / max(0.3, (nt - lt) * 0.85))
                if k <= 0: continue
                yy = p + 130 + i * 66 + (20 if i > 0 else 0)
                hl = it.get("highlight")
                if hl and k >= 1 and hl in it["text"]:
                    x0 = p + 44 + f.getlength(it["text"].split(hl)[0])
                    d.rectangle([x0 - 4, yy + 4, x0 + f.getlength(hl) + 4, yy + 48], fill=(255, 216, 90))
                d.text((p + 44, yy), it["text"][:int(len(it["text"]) * k)], font=f, fill=INK)
            if e.get("signature") and L and t > L[-1].get("_t", t0) + 1.0:
                d.text((p + 470, p + 600), e["signature"], font=font(F_XB, 44), fill=(40, 60, 160))
            k = ease_out((t - t0) / 0.45)
            paste(fr, c, e.get("x", 440), (y or 760) + (1 - k) * 400, 0.86, al * clamp(k * 2))
        elif ty == "envelope":
            k = ease_out((t - t0) / 0.4)
            ex = 600 - (1 - k) * 700 + (ease_in_out((t - e["_fly_at"]) / 0.5) * 900 if "_fly_at" in e and t > e["_fly_at"] else 0)
            paste(fr, self.ENV, ex, y or 620, 1, al)
            if "_stamp_at" in e and t > e["_stamp_at"]:
                k2 = clamp((t - e["_stamp_at"]) / 0.18)
                img = self.cached(("stamp", e.get("stamp", "RECOMMANDÉ")), lambda: make_stamp(e.get("stamp", "RECOMMANDÉ"), (220, 40, 55), 56))
                paste(fr, img, ex + 20, y or 620, 1.0 + 0.8 * (1 - ease_out(k2)), al * clamp(k2 * 3))
        elif ty == "infocard":
            c = rrect_img(700, 300, CARD, border=CARD_B); d = ImageDraw.Draw(c); p = 40
            d.text((p + 44, p + 44), e.get("small", ""), font=font(F_SB, 32), fill=(170, 180, 230))
            ts = 52
            while font(F_BLACK, ts).getlength(e.get("title", "")) > 610 and ts > 28: ts -= 2
            d.text((p + 44, p + 96), e.get("title", ""), font=font(F_BLACK, ts), fill=WHITE)
            if e.get("pill") and t > e.get("_pill_at", 1e9):
                k = back((t - e["_pill_at"]) / 0.35); g = pill(e["pill"], (46, 160, 96), size=36)
                g = g.resize((max(1, int(g.width * k)), max(1, int(g.height * k)))); c.alpha_composite(g, (p + 44, p + 190))
            paste(fr, c, e.get("x", 600), y or 1000, s, a * al)
        elif ty == "confetti":
            dd = ImageDraw.Draw(fr); R = random.Random(5)
            for i in range(40):
                tt = t - t0 - R.random() * 0.3
                if tt < 0: continue
                x = 540 + R.uniform(-1, 1) * 420 * min(1, tt * 2); yy = 300 + R.uniform(-80, 40) + 600 * tt * tt
                dd.rectangle([x, yy, x + 14, yy + 22], fill=R.choice([YEL, RED, GREEN, (120, 160, 255)]) + (int(255 * al * clamp(1.5 - tt)),))
        elif ty == "split":
            img = Image.new("RGBA", (W, 1100), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
            kl = ease_out((t - t0) / 0.4); kr = ease_out((t - e.get("_right_at", t0 + 2)) / 0.4)
            L, R_ = e.get("left", ["", "", ""]), e.get("right", ["", "", ""])
            def fit(txt, mx, sz):
                while font(F_BLACK, sz).getlength(txt) > mx and sz > 30: sz -= 2
                return font(F_BLACK, sz)
            if kl > 0:
                d.rectangle([0, 0, W // 2, 1100], fill=(60, 24, 52, int(230 * kl)))
                d.text((60, 380), L[0], font=font(F_SB, 40), fill=(230, 200, 220))
                d.text((60, 440), L[1], font=fit(L[1], 440, 62), fill=WHITE); d.text((60, 515), L[2], font=fit(L[2], 440, 62), fill=RED)
                d.rounded_rectangle([200, 140, 330, 330], 24, fill=(20, 20, 30)); d.ellipse([245, 280, 285, 320], fill=(220, 40, 55))
            if kr > 0:
                d.rectangle([W // 2, 0, W, 1100], fill=(64, 66, 96, int(230 * kr)))
                d.text((W // 2 + 60, 380), R_[0], font=font(F_SB, 40), fill=(220, 224, 250))
                d.text((W // 2 + 60, 440), R_[1], font=fit(R_[1], 440, 56), fill=WHITE); d.text((W // 2 + 60, 510), R_[2], font=fit(R_[2], 440, 62), fill=YEL)
                img.alpha_composite(self.ENV.resize((240, 157)), (W // 2 + 150, 160))
            paste(fr, img, 540, 760, 1, al)
        elif ty == "cta":
            c = rrect_img(760, 330, CARD, border=CARD_B); d = ImageDraw.Draw(c); p = 40
            d.rounded_rectangle([p + 44, p + 40, p + 716, p + 150], 30, fill=(245, 246, 252))
            q = e.get("question", ""); sz = 36
            while font(F_XB, sz).getlength(q) > 620 and sz > 22: sz -= 2
            d.text((p + 70, p + 95 - sz // 2 - 4), q, font=font(F_XB, sz), fill=(30, 34, 60))
            if t > e.get("_button_at", 1e9):
                k = back((t - e["_button_at"]) / 0.4); g = pill(e.get("button", "ABONNE-TOI"), RED, size=44)
                g = g.resize((max(1, int(g.width * k)), max(1, int(g.height * k)))); c.alpha_composite(g, (p + 380 - g.width // 2, p + 190))
            paste(fr, c, 540, y or 760, s, a * al)

    def render(self, t):
        fr = self.BG.copy()
        for strip, x, spd, off in self.RAIN:
            yv = -int((t * spd + off) % H); fr.alpha_composite(strip.crop((0, -yv, 40, -yv + H)), (x, 0))
        d = ImageDraw.Draw(fr)
        d.rectangle([0, 0, W, 10], fill=(30, 36, 80)); d.rectangle([0, 0, int(W * t / self.dur), 10], fill=YEL)
        dx = dy = 0
        for st in self.stamps:
            if st <= t < st + 0.34:
                k = 1 - (t - st) / 0.34; dx = int(math.sin(t * 90) * 14 * k); dy = int(math.cos(t * 70) * 10 * k)
        cur_scene = None
        for sc in self.scenes:
            al = window(t, sc["t0"], sc["t1"])
            if al <= 0: continue
            if sc["t0"] <= t <= sc["t1"]: cur_scene = sc
            for e in sc["els"]: self.draw_el(fr, e, t, al, dx, dy)
        if cur_scene and cur_scene["char"].get("pose") != "none":
            ch = cur_scene["char"]; pose = ch.get("pose", "idle")
            for pt, pp in cur_scene["poses"]:
                if t >= pt: pose = pp
            s, a = pop(t, cur_scene["t0"], 0.4)
            paste(fr, self.POSE.get(pose, self.POSE["idle"]), ch.get("x", 230) + dx, ch.get("y", 1250) + math.sin(t * 3.2) * 6 + dy, s, a)
        cur = None
        for tc, im in self.caps:
            if t >= tc: cur = (tc, im)
        if cur:
            s, a = pop(t, cur[0], 0.18); paste(fr, cur[1], 540, 1580, 0.85 + 0.15 * s, a)
        return fr.convert("RGB")

# ---------- audio : voix + bruitages discrets (pas de ding) ----------
SR = 44100
def build_audio(v, voice_mp3, path):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", voice_mp3, "-ac", "1", "-ar", str(SR), "_voice.wav"], check=True)
    with wave.open("_voice.wav") as w: vo = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    n = int(v.dur * SR); out = np.zeros(n, np.float32); out[:min(n, len(vo))] += vo[:n]
    rng = np.random.RandomState(2); tt = np.arange(n) / SR
    out += ((np.sin(2 * np.pi * 55 * tt) * .5 + np.sin(2 * np.pi * 82.4 * tt) * .3) * 0.025 * np.clip(tt / 1.5, 0, 1) * np.clip((v.dur - tt), 0, 1)).astype(np.float32)
    def add(sig, t0, g=1.0):
        i = int(t0 * SR); j = min(n, i + len(sig))
        if 0 <= i < n: out[i:j] += sig[: j - i] * g
    def whoosh(d=0.4):
        m = int(d * SR); x = np.convolve(rng.randn(m), np.ones(40) / 40, mode="same")
        return (x * np.sin(np.linspace(0, np.pi, m)) ** 2 * 0.22).astype(np.float32)
    def thud():
        m = int(0.4 * SR); t_ = np.arange(m) / SR
        return (np.sin(2 * np.pi * 60 * t_) * np.exp(-t_ * 10) * 0.5 + rng.randn(m) * np.exp(-t_ * 40) * 0.15).astype(np.float32)
    def tick():
        m = int(0.02 * SR); t_ = np.arange(m) / SR
        return (np.sin(2 * np.pi * 1800 * t_) * np.exp(-t_ * 260) * 0.035).astype(np.float32)
    for sc in v.scenes[1:]: add(whoosh(), max(0, sc["t0"] - 0.15))
    for st in v.stamps: add(thud(), st)
    for sc in v.scenes:
        for e in sc["els"]:
            if e["type"] in ("bigvalue", "valuecard") and "count" in e:
                for k in np.arange(0, 0.6, 0.06): add(tick(), e["_t"] + k)
            if e["type"] == "calc" and "_result_at" in e:
                for k in np.arange(0, 0.4, 0.06): add(tick(), e["_result_at"] + k)
    out = np.clip(out / max(1.0, np.abs(out).max() / 0.95), -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((out * 32767).astype(np.int16).tobytes())

# ---------- miniature (style habituel : gros titre, bandeau rouge, 2 fiches ✅/❌) ----------
def emoji_img(ch, size):
    try:
        f = ImageFont.truetype(F_EMOJI, 109)
        im = Image.new("RGBA", (160, 160), (0, 0, 0, 0)); ImageDraw.Draw(im).text((10, 10), ch, font=f, embedded_color=True)
        bb = im.getbbox(); im = im.crop(bb) if bb else im
        return im.resize((size, int(size * im.height / max(1, im.width))), Image.LANCZOS)
    except Exception:
        return Image.new("RGBA", (1, 1))

def make_thumb(cfg, out):
    th = cfg["thumb"]; fem = cfg.get("perso", "f") == "f"
    img = make_bg(); d = ImageDraw.Draw(img)
    def fit(txt, mx, sz, f=F_BLACK):
        while font(f, sz).getlength(txt) > mx and sz > 40: sz -= 4
        return font(f, sz)
    # titres
    f1 = fit(th["title1"], 960, 130); t1 = text_img(th["title1"], f1, WHITE, stroke=10)
    f2 = fit(th["title2"], 860, 150); t2 = text_img(th["title2"], f2, YEL, stroke=10)
    img.alpha_composite(t1, ((W - t1.width) // 2, 150))
    em = emoji_img(th.get("emoji", "😱"), 130)
    x2 = (W - t2.width - em.width - 20) // 2
    img.alpha_composite(t2, (x2, 150 + t1.height + 10)); img.alpha_composite(em, (x2 + t2.width + 20, 150 + t1.height + 10 + (t2.height - em.height) // 2))
    # bandeau rouge
    by = 150 + t1.height + t2.height + 60
    bt = th["banner"]; fb = fit(bt, 860, 58, F_XB); tw = fb.getlength(bt)
    d.rounded_rectangle([(W - tw) / 2 - 40, by, (W + tw) / 2 + 40, by + 100], 20, fill=RED)
    d.text(((W - tw) / 2, by + 18), bt, font=fb, fill=WHITE)
    # fiches
    def card(c, good):
        cd = rrect_img(440, 450, PAPER, r=24); dd = ImageDraw.Draw(cd); p = 40
        bigf = fit(c["big"], 280, 120); dd.text((p + 40, p + 40), c["big"], font=bigf, fill=INK)
        for i, l in enumerate(c.get("lines", [])[:2]): dd.text((p + 40, p + 200 + i * 62), l, font=fit(l, 340, 52, F_XB), fill=INK)
        dd.text((p + 40, p + 350), c.get("sub", ""), font=fit(c.get("sub", ""), 360, 34, F_SB), fill=(110, 106, 96))
        # pastille ✓ / ✗ dessinée
        cx, cy, r = p + 385, p + 60, 46
        dd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(46, 170, 96) if good else (220, 40, 55))
        if good: dd.line([cx - 22, cy, cx - 6, cy + 18, cx + 24, cy - 18], fill=WHITE, width=12, joint="curve")
        else: dd.line([cx - 18, cy - 18, cx + 18, cy + 18], fill=WHITE, width=12); dd.line([cx - 18, cy + 18, cx + 18, cy - 18], fill=WHITE, width=12)
        return cd.rotate(4 if good else -4, expand=True, resample=Image.BICUBIC)
    cy = by + 150
    ch = character("shock", fem).resize((340, 589))
    img.alpha_composite(ch, ((W - 340) // 2, H - 589 - 210))
    a = card(th["card_a"], True); b = card(th["card_b"], False)
    img.alpha_composite(b, (W - b.width + 5, cy + 50)); img.alpha_composite(a, (-5, cy))
    bt = th["bottom"]; fb = fit(bt, 900, 84)
    tb = text_img(bt, fb, WHITE, stroke=8); img.alpha_composite(tb, ((W - tb.width) // 2, H - 220))
    img.convert("RGB").save(out, quality=92)

# ---------- main ----------
def main():
    cmd = sys.argv[1]
    if cmd == "words":
        for i, w in enumerate(load_words(sys.argv[2])): print(f"{i:3d} {w['start']:6.2f} {w['text']}")
        return
    cfg = json.load(open(sys.argv[2]))
    if cmd == "thumb": make_thumb(cfg, sys.argv[3]); print("OK", sys.argv[3]); return
    if cmd == "check":
        words = load_words(sys.argv[3]); dur = words[-1]["end"] + 0.7
        v = Video(cfg, words, dur)
        for sc in v.scenes:
            print(f"[{sc['t0']:6.2f} → {sc['t1']:6.2f}] {sc['name']}  perso={sc['char'].get('pose')}")
            for e in sc["els"]: print(f"     {e['_t']:6.2f} {e['type']}")
        print("Sous-titres :", " | ".join(s for _, s in build_captions(words, cfg.get("red_words", []), cfg.get("yellow_words", []))))
        return
    voice, words = sys.argv[3], load_words(sys.argv[4]); out = sys.argv[5]
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", voice]).decode()) + 0.7
    dur = max(dur, float(cfg.get("min_duration", 64.6)))  # programme de récompense TikTok : 64 s minimum
    v = Video(cfg, words, dur)
    if cmd == "stills":
        ts = list(np.linspace(0.8, dur - 1, 16))
        ims = [v.render(x).resize((216, 384)) for x in ts]
        s = Image.new("RGB", (216 * 8, 384 * 2))
        for i, im in enumerate(ims): s.paste(im, ((i % 8) * 216, (i // 8) * 384))
        s.save(out, quality=85); print("OK", out); return
    build_audio(v, voice, "_mix.wav")
    nfr = int(dur * FPS)
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-i", "_mix.wav", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                          "-shortest", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    for i in range(nfr):
        p.stdin.write(v.render(i / FPS).tobytes())
        if i % 300 == 0: print(f"{i}/{nfr}", flush=True)
    p.stdin.close(); p.wait(); print(f"OK {out} ({dur:.1f} s)")

if __name__ == "__main__":
    main()
