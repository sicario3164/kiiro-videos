#!/usr/bin/env python3
"""Version HORIZONTALE (1920x1080) du moteur rw_engine — vidéos longues YouTube « Tes Droits Cachés ».

Usage :
  python3 rw_wide.py stills scenes.json main.mp3 main_words.json planche.jpg
  python3 rw_wide.py render scenes.json main.mp3 main_words.json sortie.mp4 [debut fin]
  python3 rw_wide.py thumb  scenes.json miniature.jpg          -> miniature YouTube 1280x720
Mêmes scenes.json que rw_engine (éléments, poses, hook, music_mood…), plus :
  "chapters": [{"at": <mots ou secondes>, "num": 1, "title": "Ce que la CAF ne dit pas"}]  -> carton de chapitre 1,8 s
Aucune barre de progression (règle absolue).
"""
import json, math, random, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw
import rw_engine as R

W, H, FPS = 1920, 1080, 30
VW, VH = R.W, R.H                       # repère des éléments (vertical 1080x1920)
CROP = (40, 215, 1080, 1260)             # zone utile des éléments dans le repère vertical
CS = 0.92                               # échelle de la zone de contenu
CX0, CY0 = 880, 18                      # coin haut-gauche de la zone de contenu
CAP_X, CAP_Y = 1360, 990                # sous-titres sous le contenu
NORA_X, NORA_Y, NORA_S = 420, 640, 1.62


def make_bg_wide():
    rnd = random.Random(7)
    y = np.linspace(0, 1, H)[:, None]
    top = np.array([13, 20, 62]); bot = np.array([6, 9, 32])
    g = np.zeros((H, W, 3), np.float32)
    for c in range(3): g[:, :, c] = top[c] * (1 - y) + bot[c] * y
    yy, xx = np.mgrid[0:H, 0:W]
    for cx, cy, k, colr in ((420, 560, 2.6, (30, 40, 100)), (1320, 470, 2.0, (18, 26, 70))):
        d = np.sqrt(((xx - cx) / W) ** 2 + ((yy - cy) / H) ** 2 * 0.35)
        g += (np.clip(1 - d * k, 0, 1) ** 2)[:, :, None] * np.array(colr)
    img = Image.fromarray(np.clip(g, 0, 255).astype(np.uint8)).convert("RGBA")
    dr = ImageDraw.Draw(img)
    for _ in range(170):
        x, yv = rnd.randint(0, W), rnd.randint(0, H)
        dr.ellipse([x, yv, x + 2, yv + 2], fill=(255, 255, 255, rnd.randint(20, 70)))
    # sol discret sous Nora
    sol = Image.new("RGBA", (700, 90), (0, 0, 0, 0))
    ImageDraw.Draw(sol).ellipse([0, 0, 699, 89], fill=(0, 0, 0, 90))
    img.alpha_composite(sol, (NORA_X - 350, 1010))
    return img


def make_rain_wide():
    rnd = random.Random(8); cols = []; f = R.font(R.F_JP, 30)
    for _ in range(22):
        strip = Image.new("RGBA", (40, H * 2), (0, 0, 0, 0)); d = ImageDraw.Draw(strip)
        for j in range(0, H * 2, 38):
            if rnd.random() < 0.55: d.text((4, j), rnd.choice(R.GLYPHS), font=f, fill=(70, 230, 140, rnd.randint(10, 34)))
        cols.append((strip, rnd.randint(30, W - 50), rnd.uniform(40, 110), rnd.randint(0, H)))
    return cols


def chapter_card(num, title):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, H], fill=(6, 8, 24, 215))
    tag = R.pill(f"CHAPITRE {num}", R.RED, size=46)
    im.alpha_composite(tag, ((W - tag.width) // 2, 330))
    sz = 110
    while R.font(R.F_BLACK, sz).getlength(title) > 1600 and sz > 50: sz -= 4
    t = R.text_img(title, R.font(R.F_BLACK, sz), R.WHITE, stroke=8)
    im.alpha_composite(t, ((W - t.width) // 2, 470))
    d.rounded_rectangle([W // 2 - 90, 470 + t.height + 40, W // 2 + 90, 470 + t.height + 52], 6, fill=R.YEL)
    return im


class WideVideo(R.Video):
    def __init__(self, cfg, words, dur):
        super().__init__(cfg, words, dur)
        self.BGW, self.RAINW = make_bg_wide(), make_rain_wide()
        self.chapters = []
        for ch in cfg.get("chapters", []):
            t0, _ = R.resolve(ch["at"], words, 0)
            self.chapters.append((t0, chapter_card(ch.get("num", len(self.chapters) + 1), ch.get("title", ""))))
        self.stamps += [t0 + 0.05 for t0, _ in self.chapters]

    def render(self, t):
        fr = self.BGW.copy()
        for strip, x, spd, off in self.RAINW:
            yv = -int((t * spd + off) % H); fr.alpha_composite(strip.crop((0, -yv, 40, -yv + H)), (x, 0))
        dx = dy = 0
        for st in self.stamps:
            if st <= t < st + 0.34:
                k = 1 - (t - st) / 0.34; dx = int(math.sin(t * 90) * 14 * k); dy = int(math.cos(t * 70) * 10 * k)
        # éléments dessinés dans le repère vertical, puis réduits à droite
        lay = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
        cur_scene = None
        for sc in self.scenes:
            al = R.window(t, sc["t0"], sc["t1"])
            if al <= 0: continue
            if sc["t0"] <= t <= sc["t1"]: cur_scene = sc
            for e in sc["els"]: self.draw_el(lay, e, t, al, dx, dy)
        lay = lay.crop(CROP)
        lay = lay.resize((int(lay.width * CS), int(lay.height * CS)), Image.BILINEAR)
        fr.alpha_composite(lay, (CX0, CY0))
        # Nora en grand à gauche
        if cur_scene and cur_scene["char"].get("pose") != "none" and self.actor is not None:
            pose = cur_scene["char"].get("pose", "idle")
            for pt, pp in cur_scene["poses"]:
                if t >= pt: pose = pp
            i = self.scenes.index(cur_scene); prev = self.scenes[i - 1]["char"] if i > 0 else None
            side = lambda c: -40 if c.get("x", 230) < 540 else 40
            xo = side(cur_scene["char"]); hop = 0.0
            if prev and prev.get("pose") != "none" and side(prev) != xo:
                k = R.clamp((t - cur_scene["t0"]) / 0.5)
                xo = side(prev) + (xo - side(prev)) * R.ease_in_out(k); hop = -40 * math.sin(math.pi * k)
            a = self.actor.frame(t, pose)
            a = a.resize((int(a.width * NORA_S), int(a.height * NORA_S)), Image.BILINEAR)
            R.paste(fr, a, NORA_X + xo + dx, NORA_Y + hop + math.sin(t * 3.2) * 4 + dy)
        # zoom lent + coup de poing de l'accroche
        if cur_scene:
            k = R.clamp((t - cur_scene["t0"]) / max(0.5, cur_scene["t1"] - cur_scene["t0"]))
            z = (1.0 + 0.03 * R.ease_in_out(k)) * R.hook_punch(t, self.cfg)
            if z > 1.002:
                cw, chh = int(W / z), int(H / z); ox, oy = (W - cw) // 2, (H - chh) // 2
                fr = fr.crop((ox, oy, ox + cw, oy + chh)).resize((W, H), Image.BILINEAR)
        # sous-titres
        cur = None
        for tc, im in self.caps:
            if t >= tc: cur = (tc, im)
        if cur:
            s, a = R.pop(t, cur[0], 0.18); R.paste(fr, cur[1], CAP_X, CAP_Y, (0.85 + 0.15 * s) * 0.92, a)
        # carton de chapitre
        for t0, card in self.chapters:
            if t0 <= t < t0 + 1.8:
                a = R.clamp((t - t0) / 0.2) * R.clamp((t0 + 1.8 - t) / 0.3)
                s = 1.0 + 0.08 * (1 - R.ease_out(R.clamp((t - t0) / 0.3)))
                R.paste(fr, card, W // 2, H // 2, s, a)
        # accroche des 2 premières secondes (rendue dans le repère vertical puis centrée)
        if self.cfg.get("hook") and R.HOOK_T0 <= t < R.HOOK_T1:
            hl = Image.new("RGBA", (VW, VH), (0, 0, 0, 0)); R.hook_overlay(hl, self.cfg, t, 760)
            bb = hl.getbbox()
            if bb:
                hc = hl.crop(bb); R.paste(fr, hc, W // 2 + (bb[0] + bb[2]) / 2 - VW / 2, H // 2 + (bb[1] + bb[3]) / 2 - 760, 1.15)
        return fr.convert("RGB")


def make_thumb_wide(cfg, out):
    th = cfg["thumb"]; TW, TH = 1280, 720
    img = make_bg_wide().resize((TW, TH), Image.LANCZOS); d = ImageDraw.Draw(img)
    def fit(txt, mx, sz, f=R.F_BLACK):
        while R.font(f, sz).getlength(txt) > mx and sz > 18: sz -= 2
        return R.font(f, sz)
    ac = R.Actor(cfg.get("perso", "nora"), np.zeros(10, np.float32), [], set())
    ch = ac.frame(0.3, "shock"); ch = ch.resize((int(ch.width * 1.25), int(ch.height * 1.25)), Image.LANCZOS)
    img.alpha_composite(ch, (-10, TH - ch.height + 60))
    x0 = 470; mx = TW - x0 - 40
    t1 = R.text_img(th["title1"], fit(th["title1"], mx, 110), R.WHITE, stroke=9)
    em = R.emoji_img(th.get("emoji", "😱"), 96)
    t2 = R.text_img(th["title2"], fit(th["title2"], mx - em.width - 20, 124), R.YEL, stroke=9)
    y = 70; img.alpha_composite(t1, (x0, y)); y += t1.height + 6
    img.alpha_composite(t2, (x0, y)); img.alpha_composite(em, (x0 + t2.width + 16, y + (t2.height - em.height) // 2)); y += t2.height + 34
    bt = th["banner"]; fb = fit(bt, mx - 60, 52, R.F_XB); tw = fb.getlength(bt)
    d.rounded_rectangle([x0, y, x0 + tw + 60, y + 88], 18, fill=R.RED); d.text((x0 + 30, y + 15), bt, font=fb, fill=R.WHITE); y += 120
    for c, good in ((th["card_a"], True), (th["card_b"], False)):
        cd = R.rrect_img(360, 200, R.PAPER, r=22, shadow=False); dd = ImageDraw.Draw(cd)
        dd.text((28, 20), c["big"], font=fit(c["big"], 220, 84), fill=R.INK)
        dd.text((28, 120), " ".join(c.get("lines", [])[:2]), font=fit(" ".join(c.get("lines", [])[:2]), 300, 38, R.F_XB), fill=R.INK)
        cx, cy_, r = 316, 44, 32
        dd.ellipse([cx - r, cy_ - r, cx + r, cy_ + r], fill=(46, 170, 96) if good else (220, 40, 55))
        if good: dd.line([cx - 15, cy_, cx - 4, cy_ + 12, cx + 16, cy_ - 12], fill=R.WHITE, width=9)
        else: dd.line([cx - 12, cy_ - 12, cx + 12, cy_ + 12], fill=R.WHITE, width=9); dd.line([cx - 12, cy_ + 12, cx + 12, cy_ - 12], fill=R.WHITE, width=9)
        cd = cd.rotate(3 if good else -3, expand=True, resample=Image.BICUBIC)
        img.alpha_composite(cd, (x0 if good else x0 + 390, y + (0 if good else 20)))
    img.convert("RGB").save(out, quality=92)


def main():
    cmd = sys.argv[1]; cfg = json.load(open(sys.argv[2]))
    if cmd == "thumb": make_thumb_wide(cfg, sys.argv[3]); print("OK", sys.argv[3]); return
    voice, words = sys.argv[3], R.load_words(sys.argv[4]); out = sys.argv[5]
    dur = R._dur(voice) + 0.7
    v = WideVideo(cfg, words, dur); v.load_voice(voice)
    if cmd == "stills":
        ts = list(np.linspace(0.5, dur - 1, 12))
        s = Image.new("RGB", (480 * 4, 270 * 3))
        for i, x in enumerate(ts): s.paste(v.render(x).resize((480, 270)), ((i % 4) * 480, (i // 4) * 270))
        s.save(out, quality=85); print("OK", out); return
    t_a = float(sys.argv[6]) if len(sys.argv) > 6 else 0.0
    t_b = float(sys.argv[7]) if len(sys.argv) > 7 else dur
    R.build_audio(v, voice, "_mix.wav")
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-ss", f"{t_a:.3f}", "-t", f"{t_b - t_a:.3f}", "-i", "_mix.wav", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                          "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    n0, n1 = int(t_a * FPS), int(t_b * FPS)
    for i in range(n0, n1):
        p.stdin.write(v.render(i / FPS).tobytes())
        if (i - n0) % 300 == 0: print(f"{i - n0}/{n1 - n0}", flush=True)
    p.stdin.close(); p.wait(); print(f"OK {out} ({t_b - t_a:.1f} s)")


if __name__ == "__main__":
    main()
