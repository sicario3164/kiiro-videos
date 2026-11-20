#!/usr/bin/env python3
"""Moteur « Ce que l'école ne t'apprend pas » — 2 styles qui alternent :
   - "papier" : dessin beige, persos ronds, bandeau fixe en haut (ex. « École = Prison »)
   - "salon"  : salon sombre et chaleureux, bonshommes blancs à tête ronde, billets
Sous-titres : un mot à la fois au centre. Zoom lent par scène. Bruitages discrets. JAMAIS de barre de progression.

Usage :
  python3 ecole_engine.py words  main_words.json
  python3 ecole_engine.py check  scenes.json main_words.json
  python3 ecole_engine.py stills scenes.json main.mp3 main_words.json planche.jpg
  python3 ecole_engine.py render scenes.json main.mp3 main_words.json sortie.mp4
  python3 ecole_engine.py thumb  scenes.json miniature.jpg
  python3 ecole_engine.py short  scenes.json main_words.json brut.mp4 miniature.jpg short.mp4  (Short ≤ 59 s par coupes "short_cut")
Options : "hook" {"text", "tag"}, "short_cut" [{"from", "to"}], "music" (true), "music_mood" (warm|chill|tense), "music_gain"
  python3 ecole_engine.py demo   scenes.json sortie.mp4 "texte du script"   (sans voix : minutage estimé)
Nécessite rw_engine.py dans le même dossier.
"""
import json, math, os, random, subprocess, sys, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rw_engine as R
from rw_engine import (font, F_BLACK, F_XB, F_SB, clamp, ease_out, ease_in_out, back, pop, paste, text_img, resolve, load_words,
                       norm, number_span, fmt_num, emoji_img, music_track, boom_sfx, hook_overlay, hook_punch, make_short, HOOK_T0)

W, H, FPS = 1080, 1920, 30
F_BI = "/usr/share/fonts/opentype/inter/Inter-BlackItalic.otf"
TOP, BOT = 330, 1590          # zone illustrée du style papier
INK = (70, 50, 38)

# ======================= personnages =======================
def _line(d, pts, w, fill, outline=None, ow=0):
    if outline:
        d.line(pts, fill=outline, width=w + 2 * ow, joint="curve")
        for p in (pts[0], pts[-1]): d.ellipse([p[0] - (w / 2 + ow), p[1] - (w / 2 + ow), p[0] + (w / 2 + ow), p[1] + (w / 2 + ow)], fill=outline)
    d.line(pts, fill=fill, width=w, joint="curve")
    for p in (pts[0], pts[-1]): d.ellipse([p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2], fill=fill)

CLOTHES = {"kid": (92, 124, 176), "teacher": (244, 243, 236), "adult": (110, 116, 128), "woman": (222, 120, 140),
           "boss": (52, 56, 70), "dad": (34, 34, 40), "son": (34, 34, 40), "girl": (200, 90, 120)}

def person(style, who="kid", pose="idle", face="neutral", mouth=None, blink=False):
    S = 2; w, h = 420 * S, 760 * S; cx = w // 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    small = who in ("kid", "son", "girl")
    k = 0.82 if small else 1.0
    def P(x, y): return (cx + x * S * k, h - (760 - y) * S * k if small else y * S)
    # repère vertical : tête en haut ~ y 40..220 ; corps 230..520 ; jambes 520..740
    head_r = 92 if style == "salon" else 86
    hy = 150
    if small: hy = 150
    if style == "salon":
        skin, outl, limb = (246, 246, 244), (20, 20, 22), (246, 246, 244)
    else:
        skin, outl, limb = (240, 190, 112), INK, (60, 50, 48)
    cloth = CLOTHES.get(who, (110, 116, 128))
    if style == "salon" and who in ("kid", "son", "adult"): cloth = (34, 34, 40)
    # jambes
    legs = {"walk": [((-28, 520), (-70, 735)), ((28, 520), (70, 735))]}.get(pose, [((-26, 520), (-34, 738)), ((26, 520), (34, 738))])
    PANTS = {"kid": (58, 66, 92), "son": (58, 66, 92), "teacher": (70, 72, 84), "adult": (48, 52, 66), "boss": (36, 38, 48), "dad": (44, 46, 58)}
    pants = PANTS.get(who)
    for a, b in legs:
        if pants:  # pantalon
            _line(d, [P(a[0], a[1] - 20), P(*b)], int((30 if style == "salon" else 24) * S * k), pants, outl, (4 if style == "salon" else 3) * S)
        elif style == "salon": _line(d, [P(*a), P(*b)], int(26 * S * k), limb, outl, 4 * S)
        else: _line(d, [P(*a), P(*b)], int(10 * S * k), limb)
    # chaussures
    for a, b in legs:
        x, y = P(*b); d.ellipse([x - 26 * S * k, y - 12 * S * k, x + 26 * S * k, y + 10 * S * k], fill=(30, 30, 34))
    # bras (positions des mains)
    sh_l, sh_r = (-70, 270), (70, 270)
    hands = {"idle": ((-92, 470), (92, 470)), "point": ((-92, 470), (190, 190)), "arms_up": ((-150, 120), (150, 120)),
             "hand_out": ((-92, 470), (205, 330)), "think": ((-92, 470), (30, 230)), "sad": ((-60, 480), (60, 480)),
             "walk": ((-110, 440), (110, 420)), "shrug": ((-170, 300), (170, 300)), "hands_hips": ((-120, 400), (120, 400))}
    hl, hr = hands.get(pose, hands["idle"])
    def elbow(s, e, side):
        mx, my = (s[0] + e[0]) / 2, (s[1] + e[1]) / 2
        return (mx + side * 22, my + 18) if pose not in ("arms_up", "point") else (mx + side * 10, my)
    arms = [(sh_l, elbow(sh_l, hl, -1), hl), (sh_r, elbow(sh_r, hr, 1), hr)]
    def draw_arms():
        for s, m, e in arms:
            if style == "salon": _line(d, [P(*s), P(*m), P(*e)], int(24 * S * k), (cloth if who in ("dad", "boss") else limb), outl, 4 * S)
            else: _line(d, [P(*s), P(*m), P(*e)], int(10 * S * k), limb)
        for s, m, e in arms:
            x, y = P(*e); r = (20 if style == "salon" else 16) * S * k
            d.ellipse([x - r, y - r, x + r, y + r], fill=skin, outline=outl, width=3 * S)
    # corps
    if style == "salon":
        d.rounded_rectangle([P(-78, 235), P(78, 540)], int(60 * S * k), fill=cloth, outline=outl, width=4 * S)
        if who in ("dad", "boss"):  # chemise + cravate
            d.polygon([P(-22, 240), P(22, 240), P(0, 300)], fill=(240, 240, 240))
            d.polygon([P(-7, 262), P(7, 262), P(10, 380), P(0, 400), P(-10, 380)], fill=(170, 40, 50))
    else:
        if who == "teacher":
            d.rounded_rectangle([P(-80, 230), P(80, 560)], int(24 * S), fill=cloth, outline=INK, width=3 * S)
            d.line([P(0, 240), P(0, 560)], fill=(200, 200, 190), width=3 * S)
        elif who in ("woman", "girl"):
            d.polygon([P(-58, 235), P(58, 235), P(98, 545), P(-98, 545)], fill=cloth, outline=INK)
        else:
            d.rounded_rectangle([P(-68, 232), P(68, 525)], int(26 * S * k), fill=cloth, outline=INK, width=3 * S)
    draw_arms()
    # tête
    x0, y0 = P(-head_r, hy - head_r); x1, y1 = P(head_r, hy + head_r)
    d.ellipse([x0, y0, x1, y1], fill=skin, outline=outl, width=(5 if style == "salon" else 4) * S)
    hc = P(0, hy)
    if style == "papier":
        if who in ("woman", "girl"):
            d.chord([x0 - 6 * S, y0 - 6 * S, x1 + 6 * S, y1 - 40 * S * k], 180, 360, fill=(110, 60, 40))
            d.rounded_rectangle([x0 - 8 * S, hc[1] - 30 * S, x0 + 26 * S, hc[1] + 110 * S * k], 14 * S, fill=(110, 60, 40))
            d.rounded_rectangle([x1 - 26 * S, hc[1] - 30 * S, x1 + 8 * S, hc[1] + 110 * S * k], 14 * S, fill=(110, 60, 40))
        else:
            for dx_ in (-22, 0, 22):  # mèches
                a = P(dx_, hy - head_r + 4); d.line([a, (a[0] + dx_ * 0.3 * S, a[1] - 26 * S * k)], fill=INK, width=4 * S)
            if who == "teacher":
                d.arc([x0 + 10 * S, y0 - 14 * S, x1 - 10 * S, y0 + 60 * S], 200, 340, fill=(150, 150, 150), width=10 * S)
    elif who in ("woman", "girl"):
        d.chord([x0, y0 - 4 * S, x1, y1 - 60 * S], 180, 360, fill=(60, 40, 34))
    # visage
    ex = 30 * S * k; ey = hc[1] - 6 * S * k; er = 9 * S * k
    def eyes(shape="dot"):
        if blink and shape in ("dot", "big"): shape = "half"
        for sx in (-1, 1):
            x = hc[0] + sx * ex
            if shape == "dot": d.ellipse([x - er, ey - er * 1.3, x + er, ey + er * 1.3], fill=(20, 20, 22))
            elif shape == "half": d.line([x - er * 1.4, ey, x + er * 1.4, ey], fill=(20, 20, 22), width=int(5 * S))
            elif shape == "big":
                d.ellipse([x - er * 1.6, ey - er * 1.9, x + er * 1.6, ey + er * 1.9], fill=(255, 255, 255), outline=(20, 20, 22), width=3 * S)
                d.ellipse([x - er * 0.7, ey - er * 0.7, x + er * 0.7, ey + er * 0.9], fill=(20, 20, 22))
    def brows(kind):
        for sx in (-1, 1):
            x = hc[0] + sx * ex; y = ey - 30 * S * k
            if kind == "angry": d.line([x - sx * 18 * S * k, y - 8 * S, x + sx * 14 * S * k, y + 8 * S], fill=(20, 20, 22), width=int(6 * S))
            elif kind == "sad": d.line([x - sx * 18 * S * k, y + 6 * S, x + sx * 14 * S * k, y - 8 * S], fill=(20, 20, 22), width=int(5 * S))
            elif kind == "up": d.arc([x - 18 * S, y - 14 * S, x + 18 * S, y + 10 * S], 200, 340, fill=(20, 20, 22), width=int(5 * S))
    my = hc[1] + 46 * S * k
    if face == "happy":
        eyes(); d.arc([hc[0] - 30 * S, my - 28 * S, hc[0] + 30 * S, my + 14 * S], 20, 160, fill=(40, 20, 20), width=int(6 * S))
    elif face == "sad":
        eyes(); brows("sad"); d.arc([hc[0] - 24 * S, my - 2 * S, hc[0] + 24 * S, my + 30 * S], 200, 340, fill=(40, 20, 20), width=int(5 * S))
    elif face == "angry":
        eyes(); brows("angry"); d.line([hc[0] - 22 * S, my + 8 * S, hc[0] + 22 * S, my + 8 * S], fill=(40, 20, 20), width=int(6 * S))
    elif face in ("shock", "sweat"):
        eyes("big"); brows("up"); d.ellipse([hc[0] - 16 * S, my - 10 * S, hc[0] + 16 * S, my + 26 * S], fill=(90, 30, 40))
        if face == "sweat":
            sx_, sy_ = hc[0] + head_r * 0.6 * S, hc[1] - head_r * 0.7 * S
            d.polygon([(sx_, sy_ - 22 * S), (sx_ - 12 * S, sy_ + 8 * S), (sx_ + 12 * S, sy_ + 8 * S)], fill=(120, 190, 240))
            d.ellipse([sx_ - 12 * S, sy_ - 4 * S, sx_ + 12 * S, sy_ + 18 * S], fill=(120, 190, 240))
    elif face == "tired":
        eyes("half"); d.line([hc[0] - 16 * S, my + 8 * S, hc[0] + 16 * S, my + 8 * S], fill=(40, 20, 20), width=int(5 * S))
    else:
        eyes(); d.line([hc[0] - 16 * S, my + 6 * S, hc[0] + 16 * S, my + 6 * S], fill=(40, 20, 20), width=int(5 * S))
    if mouth:  # bouche qui parle (synchronisée sur la voix)
        mcol = (40, 20, 20)
        d.rectangle([hc[0] - 34 * S, my - 30 * S, hc[0] + 34 * S, my + 34 * S], fill=None)
        # efface la bouche dessinée par l'expression
        d.ellipse([hc[0] - 34 * S * k, my - 14 * S * k, hc[0] + 34 * S * k, my + 32 * S * k], fill=skin)
        rw_, rh_ = {"small": (14, 7), "mid": (18, 12), "wide": (21, 17), "o": (12, 15)}[mouth]
        cy_ = my + 8 * S * k
        d.ellipse([hc[0] - rw_ * S * k, cy_ - rh_ * S * k, hc[0] + rw_ * S * k, cy_ + rh_ * S * k], fill=(90, 30, 40))
        if mouth in ("mid", "wide"):
            d.ellipse([hc[0] - rw_ * 0.6 * S * k, cy_ + rh_ * 0.1 * S * k, hc[0] + rw_ * 0.6 * S * k, cy_ + rh_ * 0.95 * S * k], fill=(220, 90, 100))
    if style == "salon" and face in ("happy", "shock", "sweat", "sad"):
        for sx in (-1, 1):
            x = hc[0] + sx * 56 * S * k; d.ellipse([x - 16 * S, my - 22 * S, x + 16 * S, my - 6 * S], fill=(250, 170, 180))
    out = img.resize((w // S, h // S), Image.LANCZOS)
    bb = out.getbbox()
    return out.crop((0, bb[1] if bb else 0, out.width, out.height)) if bb else out

# ======================= décors =======================
def _rect_noise(img, amount=6, seed=1):
    a = np.array(img).astype(np.int16); r = np.random.RandomState(seed).randint(-amount, amount + 1, a.shape[:2])[:, :, None]
    a[:, :, :3] = np.clip(a[:, :, :3] + r, 0, 255); return Image.fromarray(a.astype(np.uint8))

def bg_papier(kind, w=W, h=BOT - TOP):
    img = Image.new("RGBA", (w, h), (236, 226, 202, 255)); d = ImageDraw.Draw(img)
    rnd = random.Random(hash(kind) % 1000)
    def sky(top=(198, 214, 214), bot=(236, 226, 202)):
        for y in range(0, int(h * 0.58)):
            t = y / (h * 0.58); d.line([0, y, w, y], fill=tuple(int(a * (1 - t) + b * t) for a, b in zip(top, bot)))
        d.ellipse([w * 0.78, 60, w * 0.78 + 90, 150], fill=(246, 214, 120))
        for cx in (180, 520):
            for kk in range(3): d.ellipse([cx + kk * 40 - 50, 90 + (kk % 2) * 16, cx + kk * 40 + 30, 140 + (kk % 2) * 16], fill=(246, 242, 232))
        d.polygon([(0, h * 0.58), (w * 0.3, h * 0.5), (w * 0.6, h * 0.56), (w, h * 0.49), (w, h * 0.6), (0, h * 0.62)], fill=(190, 196, 168))
        d.rectangle([0, h * 0.6, w, h], fill=(226, 210, 172))
    def building(label, gray=False):
        c = (200, 196, 186) if not gray else (170, 170, 170)
        x0, x1, y0, y1 = 140, 940, 260, 700
        d.polygon([(x0 - 30, y0), (w / 2, y0 - 110), (x1 + 30, y0)], fill=(150, 140, 128) if not gray else (120, 120, 120))
        d.rectangle([x0, y0, x1, y1], fill=c, outline=INK, width=3)
        for r_ in range(3):
            for c_ in range(8):
                if gray and r_ == 2: continue
                xx = x0 + 40 + c_ * 95; yy = y0 + 40 + r_ * 130
                d.rectangle([xx, yy, xx + 55, yy + 80], fill=(120, 140, 150) if not gray else (90, 90, 90), outline=INK, width=2)
        d.rectangle([w / 2 - 50, y1 - 150, w / 2 + 50, y1], fill=(110, 80, 60), outline=INK, width=3)
        if label:
            f = font(F_XB, 46); tw = f.getlength(label)
            d.rectangle([w / 2 - tw / 2 - 24, y0 - 70, w / 2 + tw / 2 + 24, y0 - 6], fill=(246, 240, 226), outline=INK, width=3)
            d.text((w / 2 - tw / 2, y0 - 64), label, font=f, fill=INK)
    def wall(col=(214, 222, 196)):
        d.rectangle([0, 0, w, h * 0.66], fill=col); d.rectangle([0, h * 0.66, w, h], fill=(214, 186, 140))
        d.line([0, h * 0.66, w, h * 0.66], fill=INK, width=3)
    if kind in ("school", "street", "park", "prison"):
        sky()
        if kind in ("school", "prison"): building("ÉCOLE")
        if kind == "school":
            for x in range(0, w, 28): d.line([x, 610, x, 760], fill=(50, 46, 44), width=6)
            d.line([0, 630, w, 630], fill=(50, 46, 44), width=6)
        if kind == "park":
            d.rectangle([760, 420, 790, 760], fill=(110, 80, 60)); d.ellipse([660, 260, 890, 480], fill=(150, 170, 110), outline=INK, width=3)
    elif kind == "classroom":
        wall(); d.rectangle([300, 120, 860, 420], fill=(46, 70, 58), outline=(120, 90, 60), width=14)
        d.rectangle([60, 120, 240, 380], fill=(200, 222, 228), outline=INK, width=4); d.line([150, 120, 150, 380], fill=INK, width=3)
        d.rectangle([300, 600, 780, 650], fill=(170, 120, 80), outline=INK, width=3)
    elif kind == "board_stairs":
        d.rectangle([0, 0, w, h], fill=(40, 62, 52)); d.rectangle([20, 20, w - 20, h - 20], outline=(120, 90, 60), width=20)
        x, y = 140, 980
        for i in range(6):
            d.line([x, y, x + 130, y], fill=(235, 235, 225), width=6); d.line([x + 130, y, x + 130, y - 120], fill=(235, 235, 225), width=6)
            x += 130; y -= 120
    elif kind == "bedroom":
        d.rectangle([0, 0, w, h], fill=(120, 132, 168)); d.rectangle([0, h * 0.7, w, h], fill=(96, 92, 110))
        d.rectangle([90, 120, 330, 400], fill=(30, 40, 80), outline=INK, width=5); d.ellipse([220, 160, 280, 220], fill=(240, 236, 200))
        for _ in range(12): x_, y_ = rnd.randint(110, 310), rnd.randint(140, 380); d.ellipse([x_, y_, x_ + 4, y_ + 4], fill=(255, 255, 230))
        d.rounded_rectangle([420, 700, 980, 860], 20, fill=(220, 220, 236), outline=INK, width=4)
        d.rectangle([420, 640, 470, 860], fill=(140, 100, 70))
    elif kind == "bank":
        wall((228, 222, 206)); d.rounded_rectangle([560, 600, 1000, 900], 10, fill=(170, 120, 80), outline=INK, width=4)
        f = font(F_XB, 46); d.rectangle([700, 80, 960, 160], fill=(246, 240, 226), outline=INK, width=3); d.text((725, 92), "BANQUE", font=f, fill=INK)
    elif kind == "office":
        img = img.convert("L").convert("RGBA"); d = ImageDraw.Draw(img)
        d.rectangle([0, 0, w, h], fill=(176, 176, 176)); d.rectangle([0, h * 0.62, w, h], fill=(150, 150, 150))
        for i in range(5): d.rectangle([520 + i * 90, 260, 560 + i * 90, 760], fill=(200, 200, 200), outline=(80, 80, 80), width=3)
        d.polygon([(490, 260), (750, 150), (1010, 260)], fill=(140, 140, 140)); d.rectangle([600, 160, 900, 220], fill=(220, 220, 220))
        d.text((660, 168), "BUREAU", font=font(F_XB, 40), fill=(60, 60, 60))
    elif kind == "desk_night":
        d.rectangle([0, 0, w, h], fill=(120, 112, 128)); d.rectangle([0, h * 0.62, w, h], fill=(96, 86, 96))
        d.rectangle([200, 700, 900, 740], fill=(150, 104, 70), outline=INK, width=3)
        d.polygon([(760, 520), (840, 520), (870, 600), (730, 600)], fill=(250, 220, 140)); d.line([800, 600, 800, 700], fill=INK, width=6)
        g = Image.new("RGBA", (w, h), (0, 0, 0, 0)); ImageDraw.Draw(g).ellipse([600, 450, 1000, 850], fill=(255, 220, 140, 90))
        img.alpha_composite(g.filter(ImageFilter.GaussianBlur(60))); d = ImageDraw.Draw(img)
    else:
        sky()
    img = _rect_noise(img.convert("RGB")).convert("RGBA")
    if kind == "prison":
        d = ImageDraw.Draw(img)
        for x in range(30, w, 110): d.rectangle([x, 0, x + 26, h], fill=(50, 50, 54))
        d.rectangle([0, 40, w, 70], fill=(50, 50, 54)); d.rectangle([0, h - 90, w, h - 60], fill=(50, 50, 54))
    return img

def bg_salon(kind, w=W, h=H):
    img = Image.new("RGBA", (w, h), (60, 52, 44, 255)); d = ImageDraw.Draw(img); rnd = random.Random(hash(kind) % 997)
    if kind in ("living", "living_dark"):
        d.rectangle([0, 0, w, h], fill=(78, 68, 56)); d.rectangle([0, 1380, w, h], fill=(58, 48, 40))
        for x in range(0, w, 120): d.line([x, 0, x, 1380], fill=(84, 74, 62), width=3)
        d.rectangle([300, 230, 780, 560], fill=(50, 44, 40), outline=(36, 30, 26), width=16)
        d.polygon([(320, 540), (470, 330), (560, 430), (640, 360), (760, 540)], fill=(110, 120, 140)); d.polygon([(470, 330), (430, 390), (510, 390)], fill=(220, 224, 230))
        d.rounded_rectangle([-40, 1080, 360, 1420], 40, fill=(70, 60, 54)); d.rounded_rectangle([-40, 980, 320, 1120], 40, fill=(80, 70, 62))
        d.rectangle([880, 1020, 1000, 1380], fill=(60, 50, 42)); d.polygon([(880, 900), (1000, 900), (1030, 1010), (850, 1010)], fill=(240, 200, 120))
        g = Image.new("RGBA", (w, h), (0, 0, 0, 0)); ImageDraw.Draw(g).ellipse([700, 760, 1180, 1240], fill=(255, 210, 130, 70))
        img.alpha_composite(g.filter(ImageFilter.GaussianBlur(80))); d = ImageDraw.Draw(img)
        for i in range(5): d.rectangle([40 + i * 46, 420 + (i % 2) * 10, 76 + i * 46, 640], fill=[(120, 60, 50), (60, 90, 120), (140, 110, 60), (80, 100, 70), (110, 80, 110)][i])
        d.rectangle([20, 640, 290, 660], fill=(60, 46, 36))
        if kind == "living_dark":
            ov = Image.new("RGBA", (w, h), (0, 0, 20, 110)); img.alpha_composite(ov)
    elif kind in ("city_night", "sunset", "day"):
        if kind == "city_night": top, bot, bcol, win = (16, 18, 34), (34, 36, 60), (24, 26, 40), (240, 200, 110)
        elif kind == "sunset": top, bot, bcol, win = (250, 170, 90), (120, 70, 80), (50, 36, 50), (255, 210, 140)
        else: top, bot, bcol, win = (250, 222, 140), (240, 200, 110), (214, 170, 90), (250, 236, 190)
        for y in range(h):
            t = y / h; d.line([0, y, w, y], fill=tuple(int(a * (1 - t) + b * t) for a, b in zip(top, bot)))
        x = 0
        while x < w:
            bw, bh = rnd.randint(120, 220), rnd.randint(500, 1100)
            d.rectangle([x, h - 300 - bh, x + bw, h - 300], fill=bcol)
            for wy in range(h - 280 - bh, h - 340, 60):
                for wx in range(x + 16, x + bw - 30, 44):
                    if rnd.random() < 0.45: d.rectangle([wx, wy, wx + 22, wy + 32], fill=win)
            x += bw + rnd.randint(4, 20)
        d.rectangle([0, h - 300, w, h], fill=(40, 34, 40) if kind != "day" else (190, 160, 110))
    elif kind == "restaurant":
        d.rectangle([0, 0, w, h], fill=(70, 50, 46)); d.rectangle([0, 1250, w, h], fill=(120, 36, 40))
        d.rounded_rectangle([60, 1150, 1020, 1240], 16, fill=(150, 104, 70))
        for x in (300, 700):
            d.ellipse([x - 70, 1080, x + 70, 1150], fill=(210, 150, 70)); d.rectangle([x - 70, 1110, x + 70, 1125], fill=(90, 160, 70))
    return img

# ======================= accessoires =======================
def prop_img(p, style):
    t = p["type"]; txt = p.get("text", "")
    def label_box(s, size=44, fill=(246, 240, 226), fg=INK):
        f = font(F_XB, size); tw = int(f.getlength(s)); im = Image.new("RGBA", (tw + 60, size + 50), (0, 0, 0, 0))
        dd = ImageDraw.Draw(im); dd.rounded_rectangle([3, 3, im.width - 4, im.height - 4], 12, fill=fill, outline=fg, width=4)
        dd.text((30, 18), s, font=f, fill=fg); return im
    if t == "sign": return label_box(txt or "…")
    if t == "banknote":
        im = Image.new("RGBA", (260, 130), (0, 0, 0, 0)); dd = ImageDraw.Draw(im)
        dd.rounded_rectangle([4, 4, 256, 126], 10, fill=(150, 210, 110), outline=(40, 80, 40), width=5)
        dd.rectangle([18, 18, 242, 112], outline=(90, 150, 80), width=3); s = txt or "50 €"
        f = font(F_BLACK, 34); dd.text((130 - f.getlength(s) / 2, 44), s, font=f, fill=(30, 70, 30)); return im
    if t == "money_stack":
        im = Image.new("RGBA", (300, 240), (0, 0, 0, 0)); dd = ImageDraw.Draw(im)
        for i in range(6): dd.rounded_rectangle([20 + (i % 2) * 8, 180 - i * 28, 280 + (i % 2) * 8, 228 - i * 28], 8, fill=(150, 210, 110), outline=(40, 80, 40), width=4)
        return im
    if t == "clock":
        im = Image.new("RGBA", (220, 220), (0, 0, 0, 0)); dd = ImageDraw.Draw(im)
        dd.ellipse([6, 6, 214, 214], fill=(250, 248, 240), outline=INK, width=8)
        for a in range(12):
            r1, r2 = 84, 96; ang = a * math.pi / 6; dd.line([110 + r1 * math.sin(ang), 110 - r1 * math.cos(ang), 110 + r2 * math.sin(ang), 110 - r2 * math.cos(ang)], fill=INK, width=4)
        dd.line([110, 110, 110, 50], fill=INK, width=8); dd.line([110, 110, 160, 130], fill=INK, width=6); return im
    if t == "calendar":
        im = Image.new("RGBA", (220, 220), (0, 0, 0, 0)); dd = ImageDraw.Draw(im)
        dd.rounded_rectangle([6, 20, 214, 214], 14, fill=(250, 248, 240), outline=INK, width=5); dd.rectangle([6, 20, 214, 70], fill=(210, 60, 60))
        s = txt or "1 an"; f = font(F_BLACK, 52 if len(s) < 6 else 38); dd.text((110 - f.getlength(s) / 2, 110), s, font=f, fill=INK); return im
    if t == "grade":
        im = Image.new("RGBA", (260, 300), (0, 0, 0, 0)); dd = ImageDraw.Draw(im)
        dd.rectangle([10, 10, 250, 290], fill=(252, 250, 244), outline=INK, width=4)
        for i in range(5): dd.line([40, 200 + i * 18, 220, 200 + i * 18], fill=(180, 190, 210), width=3)
        s = txt or "3/20"; f = font(F_BLACK, 80); dd.text((130 - f.getlength(s) / 2, 50), s, font=f, fill=(210, 40, 40))
        if p.get("crossed"): dd.line([30, 40, 230, 260], fill=(210, 40, 40), width=12); dd.line([230, 40, 30, 260], fill=(210, 40, 40), width=12)
        return im
    if t == "books":
        im = Image.new("RGBA", (300, 420), (0, 0, 0, 0)); dd = ImageDraw.Draw(im); cols = [(200, 80, 70), (80, 120, 180), (220, 180, 70), (90, 160, 110), (150, 90, 160)]
        for i in range(12): dd.rounded_rectangle([20 + (i % 3) * 6, 380 - i * 32, 270 - (i % 2) * 10, 410 - i * 32], 6, fill=cols[i % 5], outline=INK, width=2)
        return im
    if t in ("thought", "bubble"):
        s = txt; f = font(F_XB, 46); tw = max(90, int(f.getlength(s))) if s else 120
        im = Image.new("RGBA", (tw + 100, 200), (0, 0, 0, 0)); dd = ImageDraw.Draw(im)
        dd.rounded_rectangle([6, 6, tw + 94, 130], 50, fill=(255, 255, 255), outline=INK, width=5)
        if t == "thought":
            dd.ellipse([40, 140, 70, 170], fill=(255, 255, 255), outline=INK, width=4); dd.ellipse([20, 176, 38, 194], fill=(255, 255, 255), outline=INK, width=3)
        else: dd.polygon([(50, 126), (40, 190), (100, 126)], fill=(255, 255, 255)); dd.line([(50, 128), (40, 190), (100, 128)], fill=INK, width=5)
        if s: dd.text((50, 36), s, font=f, fill=INK)
        else: [dd.ellipse([tw / 2 + 20 + k * 40, 56, tw / 2 + 40 + k * 40, 76], fill=INK) for k in range(3)]
        e = p.get("emoji")
        if e: im.alpha_composite(emoji_img(e, 80), (int(tw / 2 + 10), 26))
        return im
    if t in ("cross", "check"):
        im = Image.new("RGBA", (200, 200), (0, 0, 0, 0)); dd = ImageDraw.Draw(im)
        if t == "cross": dd.line([30, 30, 170, 170], fill=(220, 50, 50), width=26); dd.line([170, 30, 30, 170], fill=(220, 50, 50), width=26)
        else: dd.line([30, 110, 80, 160, 170, 40], fill=(60, 180, 90), width=28, joint="curve")
        return im
    if t == "heart":
        im = Image.new("RGBA", (160, 150), (0, 0, 0, 0)); dd = ImageDraw.Draw(im)
        dd.ellipse([10, 10, 85, 85], fill=(220, 50, 70)); dd.ellipse([75, 10, 150, 85], fill=(220, 50, 70)); dd.polygon([(14, 60), (146, 60), (80, 140)], fill=(220, 50, 70)); return im
    if t == "arrow":
        im = Image.new("RGBA", (260, 120), (0, 0, 0, 0)); dd = ImageDraw.Draw(im); c = (220, 50, 50) if p.get("color") != "green" else (60, 170, 90)
        dd.rectangle([10, 45, 180, 75], fill=c); dd.polygon([(170, 10), (250, 60), (170, 110)], fill=c)
        return im.rotate(p.get("angle", 0), expand=True, resample=Image.BICUBIC)
    if t == "phone":
        im = Image.new("RGBA", (200, 360), (0, 0, 0, 0)); dd = ImageDraw.Draw(im)
        dd.rounded_rectangle([6, 6, 194, 354], 28, fill=(30, 30, 36)); dd.rounded_rectangle([20, 40, 180, 320], 12, fill=(80, 140, 200))
        if txt: f = font(F_XB, 34); dd.text((100 - f.getlength(txt) / 2, 160), txt, font=f, fill=(255, 255, 255))
        return im
    if t == "chart_down" or t == "chart_up":
        im = Image.new("RGBA", (360, 260), (0, 0, 0, 0)); dd = ImageDraw.Draw(im)
        dd.rectangle([6, 6, 354, 254], fill=(252, 250, 244), outline=INK, width=4)
        pts = [(30, 60), (110, 120), (180, 100), (260, 190), (330, 220)] if t == "chart_down" else [(30, 220), (110, 170), (180, 190), (260, 90), (330, 50)]
        dd.line(pts, fill=(210, 50, 50) if t == "chart_down" else (60, 170, 90), width=10, joint="curve"); return im
    if t == "diploma":
        im = Image.new("RGBA", (320, 240), (0, 0, 0, 0)); dd = ImageDraw.Draw(im)
        dd.rectangle([10, 10, 310, 230], fill=(252, 246, 226), outline=(170, 130, 60), width=8)
        f = font(F_XB, 34); s = txt or "DIPLÔME"; dd.text((160 - f.getlength(s) / 2, 40), s, font=f, fill=INK)
        for i in range(3): dd.line([50, 110 + i * 26, 270, 110 + i * 26], fill=(190, 180, 160), width=4)
        dd.ellipse([230, 160, 290, 220], fill=(210, 60, 60)); return im
    if t == "crowd":
        n = p.get("n", 6); who = p.get("who", "kid"); one = person(style, who, "idle", p.get("face", "neutral")).resize((150, int(150 * 760 / 420 * 0.9)))
        im = Image.new("RGBA", (n * 120 + 60, one.height), (0, 0, 0, 0))
        for i in range(n): im.alpha_composite(one, (i * 120, 0))
        if style == "papier" or p.get("gray"): im = Image.merge("RGBA", (*Image.merge("RGB", im.split()[:3]).convert("L").convert("RGB").split(), im.getchannel("A"))) if p.get("gray") else im
        return im
    if t == "text":
        return text_img(txt, font(F_BLACK, p.get("size", 70)), tuple(p.get("color", (255, 255, 255))), stroke=6, sfill=(20, 20, 24))
    if t == "emoji":
        return emoji_img(txt, p.get("size", 140))
    return label_box(txt or t)

DEFAULT_POS = {"sign": (540, 0.18), "clock": (820, 0.25), "calendar": (850, 0.2), "grade": (720, 0.5), "banknote": (700, 0.5), "money_stack": (760, 0.62),
               "books": (300, 0.55), "thought": (700, 0.22), "bubble": (700, 0.22), "cross": (540, 0.45), "check": (540, 0.45), "heart": (540, 0.35),
               "arrow": (540, 0.4), "phone": (760, 0.5), "chart_down": (760, 0.3), "chart_up": (760, 0.3), "diploma": (720, 0.4), "crowd": (540, 0.72),
               "text": (540, 0.25), "emoji": (760, 0.25)}

# ======================= vidéo =======================
class Video:
    def __init__(self, cfg, words, dur):
        self.cfg, self.words, self.dur = cfg, words, dur
        self.default_style = cfg.get("style", "papier")
        self._c = {}
        self.scenes = []; idx = 0
        for i, sc in enumerate(cfg["scenes"]):
            t0, idx = resolve(sc.get("at", 0.0), words, idx)
            if i == 0: t0 = 0.0
            st = sc.get("style", self.default_style)
            props = []
            for p in sc.get("props", []):
                q = dict(p); q["_t"] = resolve(p["at"], words, idx)[0] if "at" in p else t0; props.append(q)
            chars = []
            for c in sc.get("chars", []):
                q = dict(c); q["_t"] = resolve(c["at"], words, idx)[0] if "at" in c else t0
                q["_changes"] = [(resolve(ch["at"], words, idx)[0], ch) for ch in c.get("changes", [])]; chars.append(q)
            spk = [(t0, sc.get("speaker", 0))] + [(resolve(x["at"], words, idx)[0], x["speaker"]) for x in sc.get("speaker_changes", [])]
            self.scenes.append({"spk": spk, "t0": t0, "style": st, "bg": sc.get("bg", "street" if st == "papier" else "living"), "props": props,
                                "chars": chars, "name": sc.get("name", ""), "stamp": sc.get("stamp")})
        for i, s in enumerate(self.scenes): s["t1"] = self.scenes[i + 1]["t0"] if i + 1 < len(self.scenes) else dur
        self.stamps = [p["_t"] for s in self.scenes for p in s["props"] if p.get("impact")]
        self.caps = self.build_caps()
        self.env = None
        self.phr = [words[0]["start"]] + [b["start"] for a, b in zip(words, words[1:]) if b["start"] - a["end"] > 0.28] if words else []

    def load_voice(self, voice):
        if voice: self.env = R.voice_envelope(voice)

    def amp(self, t):
        if self.env is None: return 0.0
        i = int(t * FPS); return float(self.env[i]) if 0 <= i < len(self.env) else 0.0

    def cur_word(self, t):
        for w in self.words:
            if w["start"] <= t < w["end"] + 0.05: return w["text"].lower()
        return ""

    def build_caps(self):
        ws = self.words; out = []; i = 0
        while i < len(ws):
            sp = number_span(ws, i)
            if sp:
                v, j = sp; euro = j < len(ws) and norm(ws[j]["text"]) in ("euros", "euro"); jj = j + (1 if euro else 0)
                out.append((ws[i]["start"], fmt_num(v) + (" €" if euro else ""))); i = jj; continue
            out.append((ws[i]["start"], ws[i]["text"].strip(".,;:!?…«»\""))); i += 1
        return out

    def cached(self, key, fn):
        if key not in self._c: self._c[key] = fn()
        return self._c[key]

    def caption(self, txt, style):
        key = ("cap", txt, style)
        def mk():
            if style == "salon":
                f = font(F_BI, 96); b = f.getbbox(txt, stroke_width=10)
                im = Image.new("RGBA", (b[2] - b[0] + 20, b[3] - b[1] + 20), (0, 0, 0, 0)); dd = ImageDraw.Draw(im)
                dd.text((10 - b[0], 10 - b[1]), txt, font=f, fill=(20, 22, 30), stroke_width=10, stroke_fill=(20, 22, 30))
                grad = Image.new("RGBA", im.size); gd = ImageDraw.Draw(grad)
                pal = [((120, 240, 190), (90, 200, 250)), ((250, 140, 200), (200, 120, 250)), ((250, 220, 120), (250, 150, 90))][hash(txt) % 3]
                for x in range(im.width):
                    t = x / max(1, im.width - 1); gd.line([x, 0, x, im.height], fill=tuple(int(a * (1 - t) + b_ * t) for a, b_ in zip(*pal)) + (255,))
                m = Image.new("L", im.size, 0); ImageDraw.Draw(m).text((10 - b[0], 10 - b[1]), txt, font=f, fill=255)
                im.paste(grad, (0, 0), m); return im
            return text_img(txt, font(F_BLACK, 74), (255, 255, 255), stroke=9, sfill=(24, 22, 22))
        return self.cached(key, mk)

    def render(self, t):
        sc = next((s for s in self.scenes if s["t0"] <= t < s["t1"]), self.scenes[-1])
        st = sc["style"]
        k = clamp((t - sc["t0"]) / max(0.5, sc["t1"] - sc["t0"])); z = (1.0 + 0.05 * ease_in_out(k)) * hook_punch(t, self.cfg)
        if st == "papier":
            area = self.cached(("bgp", sc["bg"]), lambda: bg_papier(sc["bg"])).copy(); ah = BOT - TOP; ybase = 0
        else:
            area = self.cached(("bgs", sc["bg"]), lambda: bg_salon(sc["bg"])).copy(); ah = H; ybase = 0
        dx = dy = 0
        for stt in self.stamps:
            if stt <= t < stt + 0.3:
                q = 1 - (t - stt) / 0.3; dx = int(math.sin(t * 90) * 12 * q); dy = int(math.cos(t * 70) * 9 * q)
        # personnages : celui qui parle = "speaker" (index dans chars, défaut 0, null = personne) ; "speaker_changes": [{"at", "speaker"}]
        si = 0
        for ts_, sv in sc["spk"]:
            if t >= ts_: si = sv
        speaker = sc["chars"][si] if (si is not None and 0 <= si < len(sc["chars"]) and t >= sc["chars"][si]["_t"]) else None
        a_ = self.amp(t); nph = sum(1 for p in self.phr if p <= t)
        for ci, c in enumerate(sc["chars"]):
            if t < c["_t"]: continue
            cur = dict(c)
            for ct, ch in c["_changes"]:
                if t >= ct: cur.update({kk: vv for kk, vv in ch.items() if kk != "at"})
            talking = c is speaker and a_ > 0.09
            pose = cur.get("pose", "idle")
            if c is speaker and pose == "idle" and self.env is not None and any(abs(t - w["start"]) < 0.9 for w in self.words if w["start"] <= t + 0.2):
                side = -1 if cur.get("flip") else 1
                prop_side = any((p.get("x", 540) - cur.get("x", 540)) * side > 60 for p in sc["props"] if t >= p["_t"])
                pose = ["idle", "hand_out", "idle", "point" if prop_side else "hand_out"][nph % 4]
            mouth = None
            if talking:
                rw = self.cur_word(t)
                mouth = "o" if (any(v in rw for v in ("ou", "o", "au")) and a_ > 0.2) else ("small" if a_ < 0.32 else "mid" if a_ < 0.62 else "wide")
            blink = ((t + ci * 1.37 + c.get("x", 540) * 0.003) % 3.6) < 0.12 and cur.get("face", "neutral") not in ("tired",)
            key = ("p", st, cur.get("who", "kid"), pose, cur.get("face", "neutral"), mouth, blink)
            img = self.cached(key, lambda: person(st, cur.get("who", "kid"), pose, cur.get("face", "neutral"), mouth, blink))
            scale = cur.get("scale", 1.0) * (1.2 if st == "papier" else 1.25)
            s_, a_ = pop(t, c["_t"], 0.35)
            yb = cur.get("y", 0.86) * ah
            x = cur.get("x", 540)
            if "walk_to" in cur:
                kk = ease_in_out((t - c["_t"]) / cur.get("walk_dur", 1.2)); x = x + (cur["walk_to"] - x) * kk
            im = img if cur.get("flip") is not True else img.transpose(Image.FLIP_LEFT_RIGHT)
            bob = math.sin(t * 3.0 + x * 0.01) * 5 + (math.sin(t * 13) * 4 * min(1, a_) if talking else 0)
            paste(area, im, x + dx, yb - im.height * scale / 2 + bob + dy, scale * (0.9 + 0.1 * s_), a_)
        # accessoires
        for p in sc["props"]:
            if t < p["_t"]: continue
            img = self.cached(("pr", st, json.dumps({kk: vv for kk, vv in p.items() if not kk.startswith("_")}, sort_keys=True, ensure_ascii=False)),
                              lambda: prop_img(p, st))
            dxp, dyp = DEFAULT_POS.get(p["type"], (540, 0.4))
            x = p.get("x", dxp); y = p.get("y", dyp) * ah
            pscale = p.get("scale", 1.0) * (1.4 if st == "salon" and p["type"] not in ("text", "crowd") else 1.0)
            if p.get("impact"):
                kk = clamp((t - p["_t"]) / 0.18); paste(area, img, x + dx, y + dy, pscale * (1 + 0.7 * (1 - ease_out(kk))), clamp(kk * 3))
            else:
                s_, a_ = pop(t, p["_t"], 0.3)
                fl = math.sin(t * 2.2 + x) * 4 if p["type"] in ("banknote", "thought", "bubble", "emoji") else 0
                paste(area, img, x + dx, y + fl + dy, pscale * s_, a_)
        # zoom lent
        if z > 1.002:
            cw, chh = int(area.width / z), int(area.height / z); ox, oy = (area.width - cw) // 2, int((area.height - chh) * 0.45)
            area = area.crop((ox, oy, ox + cw, oy + chh)).resize((area.width, area.height), Image.BILINEAR)
        if st == "papier":
            fr = Image.new("RGBA", (W, H), (0, 0, 0, 255)); fr.alpha_composite(area, (0, TOP))
            ban = self.cfg.get("banner")
            if ban:
                bimg = self.cached(("ban", tuple(ban)), lambda: self.banner_img(ban)); paste(fr, bimg, 540, TOP / 2 + 20)
            cy = TOP + (BOT - TOP) * 0.5
        else:
            fr = area; cy = H * 0.52
        # sous-titre : un mot à la fois
        cur = None
        for tc, s in self.caps:
            if t >= tc: cur = (tc, s)
        if cur:
            im = self.caption(cur[1], st); s_, a_ = pop(t, cur[0], 0.12)
            sc_ = min(1.0, 980 / im.width)
            paste(fr, im, 540, cy, sc_ * (0.9 + 0.1 * s_), a_)
        hook_overlay(fr, self.cfg, t, 640 if st == "papier" else 700)
        return fr.convert("RGB")

    def banner_img(self, parts):
        cols = [(255, 196, 40), (255, 255, 255), (230, 40, 40)]
        imgs = [text_img(p, font(F_BLACK, 84), cols[i % 3]) for i, p in enumerate(parts)]
        tw = sum(i.width for i in imgs) + 24 * (len(imgs) - 1); hh = max(i.height for i in imgs)
        out = Image.new("RGBA", (tw, hh), (0, 0, 0, 0)); x = 0
        for i in imgs: out.alpha_composite(i, (x, hh - i.height)); x += i.width + 24
        return out

# ======================= audio (bruitages discrets validés) =======================
SR = 44100
def build_audio(v, voice, path):
    n = int(v.dur * SR); out = np.zeros(n, np.float32)
    if voice:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", voice, "-ac", "1", "-ar", str(SR), "_voice.wav"], check=True)
        with wave.open("_voice.wav") as w: vo = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        out[:min(n, len(vo))] += vo[:n]
    rng = np.random.RandomState(2); tt = np.arange(n) / SR
    if v.cfg.get("music", True):
        vo_full = out.copy()
        out += music_track(n, SR, duck=vo_full, mood=v.cfg.get("music_mood", "warm"), seed=11) * float(v.cfg.get("music_gain", 0.085))
    def add(sig, t0, g=1.0):
        i = int(t0 * SR); j = min(n, i + len(sig))
        if 0 <= i < n: out[i:j] += sig[: j - i] * g
    def whoosh(d=0.4):
        m = int(d * SR); x = np.convolve(rng.randn(m), np.ones(40) / 40, mode="same")
        return (x * np.sin(np.linspace(0, np.pi, m)) ** 2 * 0.22).astype(np.float32)
    def thud():
        m = int(0.4 * SR); t_ = np.arange(m) / SR
        return (np.sin(2 * np.pi * 60 * t_) * np.exp(-t_ * 10) * 0.5 + rng.randn(m) * np.exp(-t_ * 40) * 0.15).astype(np.float32)
    for s in v.scenes[1:]: add(whoosh(), max(0, s["t0"] - 0.15))
    for st in v.stamps: add(thud(), st)
    if v.cfg.get("hook"): add(boom_sfx(SR), HOOK_T0, 0.5)
    out = np.clip(out / max(1.0, np.abs(out).max() / 0.95), -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((out * 32767).astype(np.int16).tobytes())

# ======================= miniature =======================
def make_thumb(cfg, out):
    th = cfg["thumb"]; st = th.get("style", cfg.get("style", "papier"))
    if st == "papier":
        img = Image.new("RGBA", (W, H), (0, 0, 0, 255)); img.alpha_composite(bg_papier(th.get("bg", "school")), (0, TOP))
    else:
        img = bg_salon(th.get("bg", "living")).copy()
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ImageDraw.Draw(ov).rectangle([0, 0, W, 760], fill=(0, 0, 0, 150)); img.alpha_composite(ov.filter(ImageFilter.GaussianBlur(30)))
    def fit(txt, mx, sz):
        while font(F_BLACK, sz).getlength(txt) > mx and sz > 40: sz -= 4
        return font(F_BLACK, sz)
    t1 = text_img(th["title1"], fit(th["title1"], 980, 130), (255, 255, 255), stroke=10, sfill=(10, 10, 10))
    t2 = text_img(th["title2"], fit(th["title2"], 860, 150), (255, 210, 63), stroke=10, sfill=(10, 10, 10))
    img.alpha_composite(t1, ((W - t1.width) // 2, 120))
    em = emoji_img(th.get("emoji", "😳"), 130); x2 = (W - t2.width - em.width - 20) // 2
    img.alpha_composite(t2, (x2, 130 + t1.height)); img.alpha_composite(em, (x2 + t2.width + 20, 130 + t1.height + (t2.height - em.height) // 2))
    by = 150 + t1.height + t2.height + 30; bt = th.get("banner", ""); fb = font(F_XB, 58); tw = fb.getlength(bt)
    if bt:
        d = ImageDraw.Draw(img); d.rounded_rectangle([(W - tw) / 2 - 40, by, (W + tw) / 2 + 40, by + 100], 20, fill=(230, 50, 60)); d.text(((W - tw) / 2, by + 18), bt, font=fb, fill=(255, 255, 255))
    for c in th.get("chars", [{"who": "kid", "face": "shock", "pose": "arms_up", "x": 540}]):
        p = person(st, c.get("who", "kid"), c.get("pose", "arms_up"), c.get("face", "shock")); sc = c.get("scale", 1.5)
        p = p.resize((int(p.width * sc), int(p.height * sc)), Image.LANCZOS); img.alpha_composite(p, (int(c.get("x", 540) - p.width / 2), int(1640 - p.height)))
    if th.get("bottom"):
        tb = text_img(th["bottom"], fit(th["bottom"], 940, 90), (255, 255, 255), stroke=8, sfill=(10, 10, 10)); img.alpha_composite(tb, ((W - tb.width) // 2, H - 230))
    img.convert("RGB").save(out, quality=92)

# ======================= main =======================
def fake_words(text, wps=3.3):
    out = []; t = 0.0
    for wtxt in text.split():
        d = max(0.18, 0.11 * len(wtxt) / 1.0 / 1.6); out.append({"text": wtxt, "start": round(t, 3), "end": round(t + d, 3), "type": "word"}); t += 1 / wps * (0.6 + 0.08 * len(wtxt))
    return out

def run(cfg, words, voice, out, dur):
    v = Video(cfg, words, dur); v.load_voice(voice); build_audio(v, voice, "_mix.wav")
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-i", "_mix.wav", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                          "-shortest", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    for i in range(int(dur * FPS)):
        p.stdin.write(v.render(i / FPS).tobytes())
        if i % 300 == 0: print(f"{i}/{int(dur * FPS)}", flush=True)
    p.stdin.close(); p.wait()
    for f in ("_voice.wav", "_mix.wav"):
        if os.path.exists(f): os.remove(f)
    print(f"OK {out} ({dur:.1f} s)")

def main():
    cmd = sys.argv[1]
    if cmd == "words":
        for i, w in enumerate(load_words(sys.argv[2])): print(f"{i:3d} {w['start']:6.2f} {w['text']}")
        return
    cfg = json.load(open(sys.argv[2]))
    if cmd == "thumb": make_thumb(cfg, sys.argv[3]); print("OK", sys.argv[3]); return
    if cmd == "short":  # python3 ecole_engine.py short scenes.json main_words.json brut.mp4 miniature.jpg sortie_short.mp4
        make_short(cfg, load_words(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6]); return
    if cmd == "demo":
        words = fake_words(sys.argv[4]); dur = max(words[-1]["end"] + 0.7, float(cfg.get("min_duration", 0)))
        run(cfg, words, None, sys.argv[3], dur); return
    if cmd == "check":
        words = load_words(sys.argv[3]); v = Video(cfg, words, words[-1]["end"] + 0.7)
        for s in v.scenes: print(f"[{s['t0']:6.2f} → {s['t1']:6.2f}] {s['style']}/{s['bg']}  {s['name']}  persos={len(s['chars'])} objets={len(s['props'])}")
        return
    voice, words, out = sys.argv[3], load_words(sys.argv[4]), sys.argv[5]
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", voice]).decode()) + 0.7
    dur = max(dur, float(cfg.get("min_duration", 64.6)))
    if cmd == "stills":
        v = Video(cfg, words, dur); v.load_voice(voice); ts = list(np.linspace(0.8, dur - 1, 16)); ims = [v.render(x).resize((216, 384)) for x in ts]
        s = Image.new("RGB", (216 * 8, 384 * 2))
        for i, im in enumerate(ims): s.paste(im, ((i % 8) * 216, (i // 8) * 384))
        s.save(out, quality=85); print("OK", out); return
    run(cfg, words, voice, out, dur)

if __name__ == "__main__":
    main()
