#!/usr/bin/env python3
"""duel_engine — format « LUI vs ELLE : qui a raison ? » en pixel art ambré (style écran cathodique).
Vertical 1080x1920, 30 i/s. Tout est dessiné en code (aucune image externe). AUCUNE barre de progression.

Commandes :
  python3 duel_engine.py stills scenes.json main.mp3 main_words.json planche.jpg
  python3 duel_engine.py render scenes.json main.mp3 main_words.json sortie.mp4
  python3 duel_engine.py thumb  scenes.json miniature.jpg
  python3 duel_engine.py demo   scenes.json sortie.mp4 "texte du script"    (sans voix, minutage estimé, musique)
  python3 duel_engine.py check  scenes.json main_words.json
  python3 duel_engine.py short  scenes.json main_words.json brut.mp4 miniature.jpg short.mp4   (version YouTube Shorts ≤ 59 s)

scenes.json :
{ "hook": {"text": "LAVE-VAISSELLE OU *À LA MAIN* ?"},          (titre géant des 2 premières secondes)
  "music_mood": "warm|tense|chill",
  "short_cut": [{"from": <mots où la coupe commence>, "to": <mots où ça reprend>}],   (version Shorts)
  "scenes": [ {"at": <mots ou s>, "headline": "TEXTE *JAUNE* EN HAUT", "items": [ ... ]} ],
  "thumb": {"title": "LAVE-VAISSELLE OU *À LA MAIN* ?", "scene": 0, "stamp": "UN SEUL A RAISON"} }
Coordonnées des items en PIXELS DE LA GRILLE 270x480 (x = centre, y = bas de l'objet ; zone utile y 90 à 450).
Chaque item : "type", "x", "y", "s" (échelle entière 1-3), "at" (apparition, mots ou s ; défaut = début de scène), "until".
Types :
  person   {who: lui|elle|mere|pere|ami, pose: stand|hold|point|shock|shrug|think, face: neutral|happy|sad|shock|angry, flip}
  portrait {who, label}                       médaillon rond avec nom dessous
  sink     {on: true}  dishwasher {on, display}  oven {on, display}  fridge  heater {label}  basin {}
  socket {}  bulb {on}  car {}  pump {display}  phone {}  box {label}   (objet générique étiqueté)
  meter    {text | from,to,suffix,dec, dur}   compteur électrique à chiffres
  counter  {from, to, prefix, suffix, dec, dur, sub}   GRAND nombre qui défile
  receipt  {title, text}   ticket   card {title, lines[]}   document
  grid     {n, filled, cols}   cases qui se remplissent (ex. 52 semaines, 166 lavages)
  balance  {left, right, tilt: -1|0|1}   drop {n}  coins {n, fall}  arrow {dir: l|r|u|d}  loop {}  question {}
  bubble   {text}   bulle de dialogue     cloud {text}   pensée
  stamp    {text, color: yellow|red|green, rot}   tampon qui claque
  label    {text, size: 1|2|3}   texte pixel
  team     {}   boutons TEAM LUI / TEAM ELLE (vote en commentaire)
  verdict  {text, color}   gros tampon final + pluie de pièces
"""
import json, math, os, random, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rw_engine as R

W, H, FPS = 1080, 1920, 30
LW, LH, K = 270, 480, 4
BG = (12, 8, 4); A1 = (52, 34, 14); A2 = (110, 72, 26); A3 = (178, 120, 44); A4 = (236, 178, 82); A5 = (255, 226, 150)
REDC = (232, 64, 52); GRN = (150, 214, 96); YEL = (255, 214, 60); INK = (28, 18, 8)
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
F_BLACK = "/usr/share/fonts/opentype/inter/InterDisplay-Black.otf"
COLS = {"yellow": YEL, "red": REDC, "green": GRN, "amber": A4}


def pfont(sz): return ImageFont.truetype(MONO, sz)


def ptext(txt, sz=8, col=A5, stroke=0):
    f = pfont(sz); w = int(f.getlength(txt)) + 2 + 2 * stroke; h = sz + 4 + 2 * stroke
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im); d.fontmode = "1"
    if stroke:
        for ox in range(-stroke, stroke + 1):
            for oy in range(-stroke, stroke + 1):
                d.text((1 + stroke + ox, 1 + oy), txt, font=f, fill=INK)
    d.text((1 + stroke, 1), txt, font=f, fill=col)
    return im


def rect(d, x0, y0, x1, y1, c): d.rectangle([x0, y0, x1, y1], fill=c)


# ---------------------------------------------------------------- personnages
SKIN = A4


def person_img(who="lui", pose="stand", face="neutral", blink=False, t=0.0):
    im = Image.new("RGBA", (56, 108), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    cx = 28
    fem = who in ("elle", "mere")
    body = A3 if fem else A1; body2 = A4 if fem else A2
    # jambes
    rect(d, cx - 7, 70, cx - 2, 100, A1 if fem else (36, 24, 10)); rect(d, cx + 2, 70, cx + 7, 100, A1 if fem else (36, 24, 10))
    rect(d, cx - 8, 100, cx - 1, 103, A5 if fem else A3); rect(d, cx + 1, 100, cx + 8, 103, A5 if fem else A3)
    # corps
    rect(d, cx - 10, 34, cx + 10, 72, body); rect(d, cx - 2, 34, cx + 2, 60, body2 if not fem else A5)
    if who == "pere": rect(d, cx - 10, 34, cx + 10, 40, A2)
    # bras selon la pose
    def arm(side, kind):
        sx = cx + side * 11
        if kind == "down": rect(d, sx - 2, 36, sx + 2, 64, body); rect(d, sx - 2, 64, sx + 2, 68, SKIN)
        elif kind == "fwd": rect(d, sx - 2, 36, sx + 2, 48, body); x1 = sx + side * 14; rect(d, min(sx, x1), 46, max(sx, x1), 50, body); rect(d, min(x1, x1 + side * 3), 45, max(x1, x1 + side * 3), 51, SKIN)
        elif kind == "up": rect(d, sx - 2, 14, sx + 2, 38, body); rect(d, sx - 2, 10, sx + 2, 14, SKIN)
        elif kind == "point": rect(d, sx - 2, 36, sx + 2, 44, body); x1 = sx + side * 18; rect(d, min(sx, x1), 38, max(sx, x1), 42, body); rect(d, min(x1, x1 + side * 5), 39, max(x1, x1 + side * 5), 41, SKIN)
        elif kind == "hip": rect(d, sx - 2, 36, sx + 2, 50, body); rect(d, sx - 1 + side * 2, 50, sx + 3 + side * 2, 56, body)
        elif kind == "chin": rect(d, sx - 2, 36, sx + 2, 48, body); rect(d, min(sx, cx + side * 3), 44, max(sx, cx + side * 3), 48, body); rect(d, cx + side * 2 - 2, 27, cx + side * 2 + 2, 31, SKIN)
    k = {"stand": ("down", "down"), "hold": ("down", "fwd"), "point": ("down", "point"), "shock": ("up", "up"),
         "shrug": ("hip", "hip"), "think": ("down", "chin")}.get(pose, ("down", "down"))
    arm(-1, k[0]); arm(1, k[1])
    if pose == "shrug":
        rect(d, cx - 16, 30, cx - 12, 36, SKIN); rect(d, cx + 12, 30, cx + 16, 36, SKIN)
    # tête
    rect(d, cx - 7, 14, cx + 7, 32, SKIN); rect(d, cx - 3, 32, cx + 3, 35, SKIN)
    hair = {"lui": (36, 24, 10), "elle": A5, "mere": (200, 170, 120), "pere": (150, 120, 80), "ami": A2}.get(who, A1)
    if who == "elle":
        rect(d, cx - 9, 10, cx + 9, 17, hair); rect(d, cx - 10, 14, cx - 6, 44, hair); rect(d, cx + 6, 14, cx + 10, 44, hair)
    elif who == "mere":
        rect(d, cx - 8, 10, cx + 8, 16, hair); rect(d, cx - 4, 5, cx + 4, 10, hair); rect(d, cx - 9, 14, cx - 7, 24, hair); rect(d, cx + 7, 14, cx + 9, 24, hair)
    elif who == "pere":
        rect(d, cx - 8, 13, cx - 5, 20, hair); rect(d, cx + 5, 13, cx + 8, 20, hair); rect(d, cx - 6, 11, cx + 6, 13, hair)
    else:
        rect(d, cx - 8, 9, cx + 8, 15, hair); rect(d, cx - 8, 15, cx - 6, 21, hair); rect(d, cx + 6, 15, cx + 8, 18, hair)
    # visage
    ey = 21
    if blink: rect(d, cx - 5, ey, cx - 2, ey, INK); rect(d, cx + 2, ey, cx + 5, ey, INK)
    else: rect(d, cx - 4, ey - 1, cx - 3, ey + 1, INK); rect(d, cx + 3, ey - 1, cx + 4, ey + 1, INK)
    if who in ("pere",): d.rectangle([cx - 6, ey - 2, cx - 1, ey + 2], outline=INK); d.rectangle([cx + 1, ey - 2, cx + 6, ey + 2], outline=INK)
    if face == "happy": rect(d, cx - 3, 27, cx + 3, 27, INK); d.point([(cx - 4, 26), (cx + 4, 26)], fill=INK)
    elif face == "sad": rect(d, cx - 3, 27, cx + 3, 27, INK); d.point([(cx - 4, 28), (cx + 4, 28)], fill=INK)
    elif face == "shock": rect(d, cx - 2, 26, cx + 2, 29, INK)
    elif face == "angry": rect(d, cx - 3, 28, cx + 3, 28, INK); rect(d, cx - 6, 17, cx - 2, 18, INK); rect(d, cx + 2, 17, cx + 6, 18, INK)
    else: rect(d, cx - 2, 27, cx + 2, 27, INK)
    return im


def portrait_img(who, label):
    r = 17; im = Image.new("RGBA", (2 * r + 6, 2 * r + 20), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.ellipse([1, 1, 2 * r + 4, 2 * r + 4], fill=(30, 20, 8), outline=A4, width=1)
    p = person_img(who, "stand").crop((8, 2, 48, 46))
    m = Image.new("L", im.size, 0); ImageDraw.Draw(m).ellipse([3, 3, 2 * r + 2, 2 * r + 2], fill=255)
    lay = Image.new("RGBA", im.size, (0, 0, 0, 0)); lay.alpha_composite(p, (r + 3 - 20, 4))
    lay.putalpha(Image.fromarray(np.minimum(np.array(lay.getchannel("A")), np.array(m))))
    im.alpha_composite(lay)
    if label:
        tl = ptext(label.upper(), 8, A4); im2 = Image.new("RGBA", (max(im.width, tl.width), im.height), (0, 0, 0, 0))
        im2.alpha_composite(im, ((im2.width - im.width) // 2, 0)); im2.alpha_composite(tl, ((im2.width - tl.width) // 2, 2 * r + 7)); im = im2
    return im


# ---------------------------------------------------------------- objets
def boxed(w, h, fill=A1, edge=A3):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w - 1, h - 1], fill=fill, outline=edge); return im, d


def prop_img(it, t, lt):
    ty = it["type"]
    if ty == "sink":
        im = Image.new("RGBA", (70, 70), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        rect(d, 0, 40, 69, 44, A3); rect(d, 8, 44, 61, 69, A1); d.rectangle([8, 44, 61, 69], outline=A2)
        rect(d, 14, 34, 56, 40, A2); rect(d, 33, 6, 37, 34, A3); rect(d, 33, 6, 50, 10, A3); rect(d, 47, 10, 50, 14, A3)
        if it.get("on", True):
            for yy in range(15, 36, 2):
                off = int((lt * 40 + yy) % 4 < 2)
                rect(d, 48 + off - 1, yy, 49 + off, yy + 1, A5)
            for k in range(4):
                x = 30 + int(((lt * 30 + k * 11) % 24)); rect(d, x, 37, x + 1, 38, A5)
        return im
    if ty == "dishwasher":
        im, d = boxed(52, 60, A1, A3); rect(d, 2, 2, 49, 11, A2)
        disp = str(it.get("display", "ECO")); im.alpha_composite(ptext(disp, 7, A5), (4, 1))
        d.rectangle([5, 15, 46, 55], outline=A2); rect(d, 18, 13, 33, 14, A4)
        if it.get("on", True):
            for k in range(6):
                x = 9 + (k * 7) % 34; y = 52 - int((lt * 20 + k * 9) % 34); d.ellipse([x, y, x + 2, y + 2], outline=A4)
        return im
    if ty == "oven":
        im, d = boxed(64, 54, A1, A3); rect(d, 2, 2, 61, 10, A2); im.alpha_composite(ptext(str(it.get("display", "")), 7, A5), (20, 1))
        d.rectangle([6, 14, 57, 48], outline=A2)
        if it.get("on", True):
            for x in range(8, 56, 2): rect(d, x, 16 + int(1.5 * math.sin(x * 0.7 + lt * 6)), x + 1, 17 + int(1.5 * math.sin(x * 0.7 + lt * 6)), REDC)
        return im
    if ty == "fridge":
        im, d = boxed(34, 70, A2, A4); rect(d, 1, 24, 32, 25, A1); rect(d, 27, 8, 29, 18, A5); rect(d, 27, 30, 29, 44, A5); return im
    if ty == "heater":
        im, d = boxed(32, 58, A2, A4); d.rectangle([6, 8, 25, 18], outline=A5)
        im.alpha_composite(ptext("°C", 7, A5), (9, 8)); rect(d, 12, 58 - 6, 19, 58 - 1, A1)
        lab = it.get("label", ""); out = Image.new("RGBA", (max(60, len(lab) * 5 + 4), 70), (0, 0, 0, 0)); out.alpha_composite(im, ((out.width - 32) // 2, 0))
        if lab: tl = ptext(lab.upper(), 6, A4); out.alpha_composite(tl, ((out.width - tl.width) // 2, 60))
        return out
    if ty == "basin":
        im = Image.new("RGBA", (40, 20), (0, 0, 0, 0)); d = ImageDraw.Draw(im); d.polygon([(0, 2), (39, 2), (34, 19), (5, 19)], fill=A2, outline=A4)
        rect(d, 3, 4, 36, 6, A5); return im
    if ty == "socket":
        im, d = boxed(24, 24, A4, A5); d.ellipse([7, 7, 16, 16], fill=A2); rect(d, 9, 11, 10, 12, INK); rect(d, 13, 11, 14, 12, INK); return im
    if ty == "bulb":
        im = Image.new("RGBA", (22, 30), (0, 0, 0, 0)); d = ImageDraw.Draw(im); on = it.get("on", True)
        d.ellipse([2, 0, 19, 17], fill=A5 if on else A2); rect(d, 7, 17, 14, 25, A3); return im
    if ty == "car":
        im = Image.new("RGBA", (80, 30), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        d.polygon([(2, 18), (14, 16), (24, 6), (52, 6), (64, 16), (78, 18), (78, 24), (2, 24)], fill=A2, outline=A3)
        rect(d, 27, 9, 38, 15, A1); rect(d, 41, 9, 51, 15, A1); d.ellipse([12, 19, 24, 30], fill=INK, outline=A3); d.ellipse([56, 19, 68, 30], fill=INK, outline=A3)
        return im
    if ty == "pump":
        im, d = boxed(30, 64, A2, A4); rect(d, 4, 4, 25, 18, A1); im.alpha_composite(ptext(str(it.get("display", "0,00€")), 6, A5), (4, 6))
        rect(d, 8, 24, 21, 34, A4); im.alpha_composite(ptext("95", 7, INK), (8, 24)); return im
    if ty == "phone":
        im, d = boxed(18, 32, A1, A4); rect(d, 3, 4, 14, 24, A3); rect(d, 7, 27, 10, 28, A4); return im
    if ty == "box":
        lab = str(it.get("label", "")); tl = ptext(lab.upper(), 7, A5); w = max(40, tl.width + 10)
        im, d = boxed(w, 34, A1, A4); im.alpha_composite(tl, ((w - tl.width) // 2, 11)); return im
    if ty == "meter":
        im, d = boxed(52, 26, A3, A5); rect(d, 4, 4, 47, 14, INK)
        txt = it.get("text") or num_txt(it, lt); im.alpha_composite(ptext(txt, 7, A5), (6, 3))
        d.polygon([(8, 17), (5, 22), (9, 21), (7, 25), (12, 19), (8, 20)], fill=INK); rect(d, 16, 20, 46, 21, A1); return im
    if ty == "receipt":
        im = Image.new("RGBA", (56, 70), (0, 0, 0, 0)); d = ImageDraw.Draw(im); rect(d, 0, 0, 55, 64, A5)
        for x in range(0, 56, 6): d.polygon([(x, 64), (x + 3, 69), (x + 6, 64)], fill=A5)
        tt = ptext(str(it.get("title", "")).upper(), 6, A1); im.alpha_composite(tt, ((56 - tt.width) // 2, 3))
        for y in range(14, 40, 5): rect(d, 5, y, 50, y, A3)
        v = it.get("text") or num_txt(it, lt); tv = ptext(v, 10, INK); im.alpha_composite(tv, ((56 - tv.width) // 2, 44)); return im
    if ty == "card":
        im = Image.new("RGBA", (70, 62), (0, 0, 0, 0)); d = ImageDraw.Draw(im); rect(d, 0, 0, 69, 61, A5)
        tt = ptext(str(it.get("title", "")).upper(), 8, INK); im.alpha_composite(tt, ((70 - tt.width) // 2, 4))
        y = 18
        for ln in it.get("lines", [])[:5]:
            tl = ptext(str(ln).upper(), 6, A1); im.alpha_composite(tl, ((70 - tl.width) // 2, y)); y += 9
        return im
    if ty == "grid":
        n = int(it.get("n", 52)); cols = int(it.get("cols", 13)); rows = (n + cols - 1) // cols; cs = 7
        fill = it.get("filled", n); dur = float(it.get("dur", 1.6)); k = int(min(fill, fill * R.clamp(lt / dur)))
        im = Image.new("RGBA", (cols * cs, rows * cs), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        for i in range(n):
            x, y = (i % cols) * cs, (i // cols) * cs
            if i < k: rect(d, x, y, x + cs - 2, y + cs - 2, REDC if it.get("red") else A4)
            else: d.rectangle([x, y, x + cs - 2, y + cs - 2], outline=A2)
        return im
    if ty == "balance":
        im = Image.new("RGBA", (130, 60), (0, 0, 0, 0)); d = ImageDraw.Draw(im); tilt = it.get("tilt", 0) * R.ease_out(R.clamp(lt / 0.6))
        rect(d, 63, 18, 66, 56, A3); rect(d, 48, 56, 81, 59, A3)
        y1, y2 = 18 - tilt * 8, 18 + tilt * 8; d.line([(20, y1), (110, y2)], fill=A4, width=2)
        for xx, yy, lab in ((20, y1, it.get("left", "")), (110, y2, it.get("right", ""))):
            d.line([(xx, yy), (xx - 8, yy + 14)], fill=A3); d.line([(xx, yy), (xx + 8, yy + 14)], fill=A3); rect(d, xx - 10, int(yy) + 14, xx + 10, int(yy) + 15, A4)
            tl = ptext(str(lab), 7, A5); im.alpha_composite(tl, (int(xx - tl.width / 2), int(yy) + 17))
        return im
    if ty == "drop":
        n = int(it.get("n", 1)); im = Image.new("RGBA", (n * 12, 16), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        for i in range(n):
            if lt < i * 0.08: continue
            x = i * 12; d.polygon([(x + 5, 0), (x + 1, 8), (x + 5, 14), (x + 9, 8)], fill=A5); d.ellipse([x + 1, 6, x + 9, 14], fill=A5)
        return im
    if ty == "coins":
        n = int(it.get("n", 5)); im = Image.new("RGBA", (24, n * 4 + 6), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        for i in range(n):
            if lt < i * 0.06: continue
            y = im.height - 6 - i * 4; d.ellipse([1, y, 22, y + 5], fill=A4, outline=A2)
        return im
    if ty == "arrow":
        im = Image.new("RGBA", (30, 30), (0, 0, 0, 0)); d = ImageDraw.Draw(im); d.polygon([(2, 12), (18, 12), (18, 5), (28, 15), (18, 25), (18, 18), (2, 18)], fill=A4)
        return im.rotate({"r": 0, "u": 90, "l": 180, "d": 270}.get(it.get("dir", "r"), 0))
    if ty == "loop":
        im = Image.new("RGBA", (40, 40), (0, 0, 0, 0)); d = ImageDraw.Draw(im); a0 = (lt * 120) % 360
        d.arc([4, 4, 35, 35], a0, a0 + 290, fill=A5, width=3); return im
    if ty == "question":
        return ptext("?", 34, YEL, 1)
    if ty in ("bubble", "cloud"):
        tl = ptext("« " + it.get("text", "") + " »" if ty == "bubble" else it.get("text", ""), 8, INK); w, h = tl.width + 12, tl.height + 8
        im = Image.new("RGBA", (w, h + 6), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        if ty == "bubble": rect(d, 0, 0, w - 1, h - 1, A5); d.polygon([(w // 2 - 4, h - 1), (w // 2 + 4, h - 1), (w // 2 + 6, h + 5)], fill=A5)
        else: d.rounded_rectangle([0, 0, w - 1, h - 1], 6, fill=A5)
        im.alpha_composite(tl, (6, 4)); return im
    if ty == "label":
        return ptext(it.get("text", ""), {1: 8, 2: 11, 3: 16}.get(int(it.get("size", 2)), 10), COLS.get(it.get("color", "amber"), A4), 1 if int(it.get("size", 2)) >= 2 else 0)
    if ty == "counter":
        tv = ptext(num_txt(it, lt), 26, YEL if it.get("color") != "red" else REDC, 1)
        sub = it.get("sub"); im = Image.new("RGBA", (max(tv.width, 10), tv.height + (14 if sub else 0)), (0, 0, 0, 0)); im.alpha_composite(tv, ((im.width - tv.width) // 2, 0))
        if sub:
            ts = ptext(sub.upper(), 8, A4); im2 = Image.new("RGBA", (max(im.width, ts.width), im.height), (0, 0, 0, 0)); im2.alpha_composite(im, ((im2.width - im.width) // 2, 0)); im2.alpha_composite(ts, ((im2.width - ts.width) // 2, tv.height + 2)); im = im2
        return im
    if ty == "team":
        a, b = ptext(" TEAM LUI ", 12, INK), ptext(" TEAM ELLE ", 12, INK); im = Image.new("RGBA", (a.width + b.width + 22, 22), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        rect(d, 0, 0, a.width + 3, 20, A4); rect(d, a.width + 18, 0, a.width + b.width + 21, 20, A5)
        im.alpha_composite(a, (2, 2)); im.alpha_composite(b, (a.width + 20, 2)); im.alpha_composite(ptext("OU", 7, A4), (a.width + 6, 6)); return im
    return None


def num_txt(it, lt):
    a, b = float(it.get("from", 0)), float(it.get("to", it.get("from", 0))); k = R.ease_out(R.clamp(lt / float(it.get("dur", 1.2))))
    v = a + (b - a) * k; dec = int(it.get("dec", 0))
    s = f"{v:,.{dec}f}".replace(",", " ").replace(".", ",")
    return f"{it.get('prefix', '')}{s}{it.get('suffix', '')}"


def stamp_img(text, col, rot):
    tl = ptext(text.upper(), 10, col); w, h = tl.width + 8, tl.height + 6
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im); d.rectangle([0, 0, w - 1, h - 1], outline=col); d.rectangle([1, 1, w - 2, h - 2], outline=col)
    im.alpha_composite(tl, (4, 3)); return im.rotate(rot, expand=True, resample=Image.NEAREST)


# ---------------------------------------------------------------- texte haut (pleine résolution)
def headline_img(text, size=64, maxw=980):
    toks = hook_parse(text)
    f = ImageFont.truetype(F_BLACK, size)
    while sum(f.getlength(w + " ") for w, _ in toks) > maxw * 2.6 and size > 34: size -= 4; f = ImageFont.truetype(F_BLACK, size)
    lines, cur, cw = [], [], 0; sp = f.getlength(" ")
    for w, a in toks:
        ww = f.getlength(w)
        if cur and cw + sp + ww > maxw: lines.append(cur); cur, cw = [], 0
        cur.append((w, a, ww)); cw += (sp if len(cur) > 1 else 0) + ww
    if cur: lines.append(cur)
    asc, des = f.getmetrics(); lh = int((asc + des) * 1.02)
    im = Image.new("RGBA", (W, lh * len(lines) + 40), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        tw = sum(x[2] for x in ln) + sp * (len(ln) - 1); x = (W - tw) / 2
        for w, a, ww in ln:
            d.text((x, 20 + i * lh), w, font=f, fill=YEL if a else A5); x += ww + sp
    glow = im.filter(ImageFilter.GaussianBlur(14)); out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    g = np.array(glow).astype(np.float32); g[:, :, 3] *= 0.9; out.alpha_composite(Image.fromarray(g.astype(np.uint8))); out.alpha_composite(im)
    return out


def hook_parse(text):
    res, acc = [], False
    for w in text.split():
        if w.startswith("*"): acc = True
        res.append((w.replace("*", ""), acc))
        if w.endswith("*"): acc = False
    return res




# ---------------------------------------------------------------- vidéo
class Duel:
    def __init__(self, cfg, words, dur):
        self.cfg, self.words, self.dur = cfg, words, dur
        self.scenes = []
        for i, sc in enumerate(cfg["scenes"]):
            t0, _ = R.resolve(sc["at"], words, 0) if i else (0.0, 0)
            self.scenes.append(dict(sc, t0=t0))
        for i, sc in enumerate(self.scenes):
            sc["t1"] = self.scenes[i + 1]["t0"] if i + 1 < len(self.scenes) else dur
            for it in sc.get("items", []):
                it["_t"] = R.resolve(it["at"], words, 0)[0] if "at" in it else sc["t0"]
                it["_u"] = R.resolve(it["until"], words, 0)[0] if "until" in it else sc["t1"]
        self.cache = {}; self.events = []
        for sc in self.scenes:
            for it in sc.get("items", []):
                if it["type"] in ("stamp", "verdict"): self.events.append((it["_t"], "thud"))
                elif it["_t"] > sc["t0"] + 0.05: self.events.append((it["_t"], "blip"))
            self.events.append((sc["t0"], "blip"))
        self.scan = self.make_overlay()
        self.coins = [(random.Random(i).randint(0, LW), random.Random(i * 7).uniform(0, 1.2), random.Random(i * 3).uniform(60, 140)) for i in range(40)]

    def make_overlay(self):
        a = np.zeros((H, W), np.float32); a[::4, :] = 0.16; a[1::4, :] = 0.08
        yy, xx = np.mgrid[0:H, 0:W]; d = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H / 2) / (H * 0.62)) ** 2)
        a = np.clip(a + np.clip(d - 0.55, 0, 1) * 0.9, 0, 0.95)
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); im.putalpha(Image.fromarray((a * 255).astype(np.uint8))); return im

    def hl(self, text, size=64):
        k = ("hl", text, size)
        if k not in self.cache: self.cache[k] = headline_img(text, size)
        return self.cache[k]

    def item_img(self, it, t, lt):
        ty = it["type"]
        if ty == "person":
            blink = ((t + it.get("x", 0) * 0.013) % 3.4) < 0.12
            k = ("pe", it.get("who"), it.get("pose"), it.get("face"), blink)
            if k not in self.cache: self.cache[k] = person_img(it.get("who", "lui"), it.get("pose", "stand"), it.get("face", "neutral"), blink)
            im = self.cache[k]; return im.transpose(Image.FLIP_LEFT_RIGHT) if it.get("flip") else im
        if ty == "portrait":
            k = ("po", it.get("who"), it.get("label"))
            if k not in self.cache: self.cache[k] = portrait_img(it.get("who", "lui"), it.get("label", ""))
            return self.cache[k]
        if ty in ("stamp", "verdict"):
            k = ("st", it.get("text"), it.get("color"), it.get("rot", -6), ty)
            if k not in self.cache:
                s = stamp_img(it.get("text", ""), COLS.get(it.get("color", "yellow" if ty == "stamp" else "green"), YEL), it.get("rot", -6))
                if ty == "verdict": s = s.resize((s.width * 2, s.height * 2), Image.NEAREST)
                self.cache[k] = s
            return self.cache[k]
        animated = ty in ("sink", "dishwasher", "oven", "meter", "receipt", "grid", "balance", "drop", "coins", "loop", "counter")
        if not animated:
            k = ("pr", json.dumps({a: b for a, b in it.items() if not a.startswith("_")}, sort_keys=True, ensure_ascii=False))
            if k not in self.cache: self.cache[k] = prop_img(it, t, lt)
            return self.cache[k]
        return prop_img(it, t, lt)

    def low_frame(self, t):
        lay = Image.new("RGBA", (LW, LH), BG + (255,)); d = ImageDraw.Draw(lay)
        sc = next((s for s in self.scenes if s["t0"] <= t < s["t1"]), self.scenes[-1])
        if sc.get("floor", True):
            for fy in sc.get("floors", [452]): rect(d, 8, fy, LW - 9, fy, A2)
        if sc.get("divider"):
            for x in range(10, LW - 10, 4): rect(d, x, 268, x + 1, 268, A2)
        shake = 0
        for it in sc.get("items", []):
            if not (it["_t"] <= t < it["_u"]): continue
            lt = t - it["_t"]; im = self.item_img(it, t, lt)
            if im is None: continue
            s = int(it.get("s", 1)); im = im.resize((im.width * s, im.height * s), Image.NEAREST) if s > 1 else im
            x = int(it.get("x", LW // 2) - im.width / 2); y = int(it.get("y", 400) - im.height)
            if it["type"] == "person": y += int(round(math.sin(t * 2.6 + x) * 0.6))
            if it["type"] in ("stamp", "verdict"):
                k = R.clamp(lt / 0.16)
                if k < 1:
                    z = 1 + 1.6 * (1 - k); im = im.resize((max(1, int(im.width * z)), max(1, int(im.height * z))), Image.NEAREST)
                    x = int(it.get("x", LW // 2) - im.width / 2); y = int(it.get("y", 300) - im.height)
                if lt < 0.3: shake = 2
            elif lt < 0.35 and it["type"] not in ("person",):
                # apparition en dither (pixels qui s'allument)
                rng = np.random.RandomState(abs(hash((it["type"], it.get("x"), it.get("y")))) % 2 ** 31)
                m = (rng.rand(im.height, im.width) < (lt / 0.35)).astype(np.uint8) * 255
                a = np.minimum(np.array(im.getchannel("A")), m); im = im.copy(); im.putalpha(Image.fromarray(a))
            lay.alpha_composite(im, (x, y))
            if it["type"] == "verdict":
                for cx0, ct, sp in self.coins:
                    yy = int((lt - ct) * sp) - 10
                    if 0 <= yy < LH and lt > ct: d.ellipse([cx0, yy, cx0 + 5, yy + 3], fill=A4)
        return lay, sc, shake

    def render(self, t):
        lay, sc, shake = self.low_frame(t)
        big = lay.resize((W, H), Image.NEAREST)
        small = lay.resize((LW // 2, LH // 2), Image.BILINEAR).filter(ImageFilter.GaussianBlur(3)).resize((W, H), Image.BILINEAR)
        arr = np.array(big.convert("RGB")).astype(np.float32) + np.array(small.convert("RGB")).astype(np.float32) * 0.55
        flick = 1.0 + 0.02 * math.sin(t * 37) + 0.015 * math.sin(t * 11)
        fr = Image.fromarray(np.clip(arr * flick, 0, 255).astype(np.uint8)).convert("RGBA")
        if shake: fr = fr.transform(fr.size, Image.AFFINE, (1, 0, random.randint(-shake, shake) * 3, 0, 1, random.randint(-shake, shake) * 3))
        # titre en haut
        if self.cfg.get("hook") and t < 2.0:
            him = self.hl(self.cfg["hook"]["text"], 118); k = R.clamp((t - 0.05) / 0.25)
            z = 1 + 0.25 * (1 - R.ease_out(k)); R.paste(fr, him, W // 2, 110 + him.height / 2, z, k)
        elif sc.get("headline"):
            him = self.hl(sc["headline"]); a = R.clamp((t - sc["t0"]) / 0.15)
            R.paste(fr, him, W // 2, 175, 1.0, a)
        fr.alpha_composite(self.scan)
        return fr.convert("RGB")

    def build_audio(self, voice, out):
        sr = 44100; n = int(self.dur * sr); mix = np.zeros(n, np.float32)
        if voice:
            raw = subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", voice, "-f", "s16le", "-ac", "1", "-ar", str(sr), "-"])
            v = np.frombuffer(raw, np.int16).astype(np.float32) / 32768; mix[:min(n, len(v))] += v[:n]
        def blip(f0, dur, vol, slide=1.0):
            tt = np.arange(int(dur * sr)) / sr; f = f0 * (slide ** (tt / dur)); ph = 2 * np.pi * np.cumsum(f) / sr
            return (np.sign(np.sin(ph)) * vol * np.exp(-tt * 18)).astype(np.float32)
        for t0, kind in self.events:
            s = blip(880, 0.07, 0.035, 1.5) if kind == "blip" else blip(110, 0.25, 0.12, 0.5)
            i = int(t0 * sr); mix[i:i + len(s)] += s[:max(0, n - i)]
        pcm = (np.clip(mix, -1, 1) * 32767).astype(np.int16)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "-", out], input=pcm.tobytes(), check=True)


def encode(v, out, voice):
    v.build_audio(voice, "_duel_mix.wav")
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-i", "_duel_mix.wav", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                          "-shortest", "-movflags", "+faststart", out + ".tmp.mp4"], stdin=subprocess.PIPE)
    n = int(v.dur * FPS)
    for i in range(n):
        p.stdin.write(v.render(i / FPS).tobytes())
        if i % 300 == 0: print(f"{i}/{n}", flush=True)
    p.stdin.close()
    if p.wait() == 0:
        tmp = out + ".tmp.mp4"; mood = v.cfg.get("music_mood", "warm")
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "rw_engine.py"), "music", tmp, out, mood])
        if r.returncode != 0: os.replace(tmp, out)
        elif os.path.exists(tmp): os.remove(tmp)
    print("OK", out, f"{v.dur:.1f} s")


def sheet(v, out, n=12):
    ts = list(np.linspace(0.3, v.dur - 0.5, n)); s = Image.new("RGB", (270 * 6, 480 * ((n + 5) // 6)))
    for i, x in enumerate(ts): s.paste(v.render(x).resize((270, 480)), ((i % 6) * 270, (i // 6) * 480))
    s.save(out, quality=85); print("OK", out)


def make_thumb(cfg, out):
    th = cfg.get("thumb", {}); words = [{"text": "x", "start": 0, "end": 1}]
    sc = dict(cfg["scenes"][th.get("scene", 0)]); sc["at"] = 0; sc["headline"] = ""
    for it in sc.get("items", []): it.pop("at", None); it.pop("until", None)
    v = Duel({"scenes": [sc]}, words, 5.0); fr = v.render(4.0).convert("RGBA")
    him = headline_img(th.get("title", cfg.get("hook", {}).get("text", "")), 120); R.paste(fr, him, W // 2, 110 + him.height / 2)
    if th.get("stamp"):
        st = stamp_img(th["stamp"], YEL, -6); st = st.resize((st.width * 5, st.height * 5), Image.NEAREST); R.paste(fr, st, W // 2, 1075)
    fr.convert("RGB").save(out, quality=92); print("OK", out)


def main():
    cmd = sys.argv[1]; cfg = json.load(open(sys.argv[2]))
    if cmd == "thumb": make_thumb(cfg, sys.argv[3]); return
    if cmd == "short":   # short scenes.json main_words.json brut.mp4 miniature.jpg sortie.mp4  (coupe "short_cut", ≤ 59 s)
        R.make_short(cfg, R.load_words(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6]); return
    if cmd == "demo":
        import ecole_engine as E
        words = E.fake_words(sys.argv[4]); dur = words[-1]["end"] + 1.0
        v = Duel(cfg, words, dur)
        if sys.argv[3].endswith(".jpg"): sheet(v, sys.argv[3], 18); return
        encode(v, sys.argv[3], None); return
    if cmd == "check":
        words = R.load_words(sys.argv[3]); bad = 0
        for sc in cfg["scenes"]:
            for a in [sc.get("at")] + [it.get("at") for it in sc.get("items", [])] + [it.get("until") for it in sc.get("items", [])]:
                if isinstance(a, str):
                    try: R.resolve(a, words, 0)
                    except ValueError: print("INTROUVABLE :", a); bad += 1
        print("OK" if not bad else f"{bad} ancre(s) à corriger"); return
    voice, words, out = sys.argv[3], R.load_words(sys.argv[4]), sys.argv[5]
    dur = R._dur(voice) + 0.8; v = Duel(cfg, words, dur)
    if cmd == "stills": sheet(v, out, 18); return
    encode(v, out, voice)


if __name__ == "__main__":
    main()
