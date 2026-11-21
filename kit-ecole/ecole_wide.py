#!/usr/bin/env python3
"""Version HORIZONTALE (1920x1080) du moteur ecole_engine — vidéos longues YouTube « Hors Programme ».

Usage :
  python3 ecole_wide.py stills scenes.json main.mp3 main_words.json planche.jpg
  python3 ecole_wide.py render scenes.json main.mp3 main_words.json sortie.mp4
  python3 ecole_wide.py thumb  scenes.json miniature.jpg            -> miniature YouTube 1280x720
  python3 ecole_wide.py demo   scenes.json planche.jpg "texte"       -> planche sans voix (minutage estimé)
Mêmes scenes.json que ecole_engine (styles papier/salon, chars, props, speaker…), plus :
  "chapters": [{"at": <mots ou secondes>, "num": 1, "title": "..."}]  -> carton de chapitre 1,8 s
Les positions x (100-980) du format vertical sont étalées sur la largeur. Aucune barre de progression.
"""
import json, math, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rw_engine as R
import ecole_engine as E
from rw_wide import chapter_card

W, H, FPS = 1920, 1080, 30
SPREAD = 1.45
BAN_H = 120                      # bandeau du style papier


def extend_wide(narrow, Wt, Ht, seed=3):
    """Agrandit un décor vertical en 16:9 : décor centré, côtés prolongés à partir des bords, vignette douce."""
    s = Ht / narrow.height
    n = narrow.resize((max(1, int(narrow.width * s)), Ht), Image.LANCZOS).convert("RGB")
    a = np.array(n).astype(np.float32); wn = a.shape[1]; side = (Wt - wn) // 2
    L = np.repeat(a[:, 2:12].mean(1, keepdims=True), side, 1); Rr = np.repeat(a[:, -12:-2].mean(1, keepdims=True), Wt - wn - side, 1)
    out = np.concatenate([L, a, Rr], 1)
    xs = np.arange(Wt)[None, :, None]
    d = np.clip(np.maximum(side - xs, xs - (side + wn)) / max(1, side), 0, 1)
    out = out * (1 - 0.28 * d)
    noise = np.random.RandomState(seed).randint(-5, 6, out.shape[:2])[:, :, None]
    m = (d > 0).astype(np.float32)
    out = np.clip(out + noise * m, 0, 255).astype(np.uint8)
    img = Image.fromarray(out).convert("RGBA")
    # raccord doux
    for x0 in (side, side + wn):
        strip = img.crop((x0 - 30, 0, x0 + 30, Ht)).filter(ImageFilter.GaussianBlur(10)); img.paste(strip, (x0 - 30, 0))
    return img, s


def wide_bg(style, kind, Ha):
    if style == "salon" and kind in ("city_night", "sunset", "day"):
        sw = int(W / (Ha / 1920.0))
        return E.bg_salon(kind, w=sw, h=1920).resize((W, Ha), Image.LANCZOS), Ha / 1920.0
    narrow = E.bg_papier(kind) if style == "papier" else E.bg_salon(kind)
    return extend_wide(narrow, W, Ha)


def X(x): return W / 2 + (x - 540) * SPREAD


class WideEcole(E.Video):
    def __init__(self, cfg, words, dur):
        super().__init__(cfg, words, dur)
        self.chapters = []
        for ch in cfg.get("chapters", []):
            t0, _ = R.resolve(ch["at"], words, 0)
            self.chapters.append((t0, chapter_card(ch.get("num", len(self.chapters) + 1), ch.get("title", ""))))

    def render(self, t):
        sc = next((s for s in self.scenes if s["t0"] <= t < s["t1"]), self.scenes[-1])
        st = sc["style"]; Ha = H - BAN_H if st == "papier" else H
        k = R.clamp((t - sc["t0"]) / max(0.5, sc["t1"] - sc["t0"])); z = (1.0 + 0.04 * R.ease_in_out(k)) * R.hook_punch(t, self.cfg)
        area, s = self.cached(("wbg", st, sc["bg"]), lambda: wide_bg(st, sc["bg"], Ha)); area = area.copy()
        ah_src = (E.BOT - E.TOP) if st == "papier" else E.H
        dx = dy = 0
        for stt in self.stamps:
            if stt <= t < stt + 0.3:
                q = 1 - (t - stt) / 0.3; dx = int(math.sin(t * 90) * 12 * q); dy = int(math.cos(t * 70) * 9 * q)
        si = 0
        for ts_, sv in sc["spk"]:
            if t >= ts_: si = sv
        speaker = sc["chars"][si] if (si is not None and 0 <= si < len(sc["chars"]) and t >= sc["chars"][si]["_t"]) else None
        amp = self.amp(t); nph = sum(1 for p in self.phr if p <= t)
        for ci, c in enumerate(sc["chars"]):
            if t < c["_t"]: continue
            cur = dict(c)
            for ct, ch in c["_changes"]:
                if t >= ct: cur.update({kk: vv for kk, vv in ch.items() if kk != "at"})
            talking = c is speaker and amp > 0.09
            pose = cur.get("pose", "idle")
            if c is speaker and pose == "idle" and self.env is not None and any(abs(t - w["start"]) < 0.9 for w in self.words if w["start"] <= t + 0.2):
                side = -1 if cur.get("flip") else 1
                prop_side = any((p.get("x", 540) - cur.get("x", 540)) * side > 60 for p in sc["props"] if t >= p["_t"])
                pose = ["idle", "hand_out", "idle", "point" if prop_side else "hand_out"][nph % 4]
            mouth = None
            if talking:
                rw = self.cur_word(t)
                mouth = "o" if (any(v in rw for v in ("ou", "o", "au")) and amp > 0.2) else ("small" if amp < 0.32 else "mid" if amp < 0.62 else "wide")
            blink = ((t + ci * 1.37 + c.get("x", 540) * 0.003) % 3.6) < 0.12 and cur.get("face", "neutral") not in ("tired",)
            key = ("p", st, cur.get("who", "kid"), pose, cur.get("face", "neutral"), mouth, blink)
            img = self.cached(key, lambda: E.person(st, cur.get("who", "kid"), pose, cur.get("face", "neutral"), mouth, blink))
            scale = cur.get("scale", 1.0) * (1.2 if st == "papier" else 1.25) * s * 1.08
            s_, a_ = R.pop(t, c["_t"], 0.35)
            yb = cur.get("y", 0.86) * Ha
            x = cur.get("x", 540)
            if "walk_to" in cur:
                kk = R.ease_in_out((t - c["_t"]) / cur.get("walk_dur", 1.2)); x = x + (cur["walk_to"] - x) * kk
            im = img if cur.get("flip") is not True else img.transpose(Image.FLIP_LEFT_RIGHT)
            bob = math.sin(t * 3.0 + x * 0.01) * 4 + (math.sin(t * 13) * 3 * min(1, amp) if talking else 0)
            R.paste(area, im, X(x) + dx, yb - im.height * scale / 2 + bob + dy, scale * (0.9 + 0.1 * s_), a_)
        for p in sc["props"]:
            if t < p["_t"]: continue
            img = self.cached(("pr", st, json.dumps({kk: vv for kk, vv in p.items() if not kk.startswith("_")}, sort_keys=True, ensure_ascii=False)),
                              lambda: E.prop_img(p, st))
            dxp, dyp = E.DEFAULT_POS.get(p["type"], (540, 0.4))
            x = X(p.get("x", dxp)); y = p.get("y", dyp) * Ha
            pscale = p.get("scale", 1.0) * (1.4 if st == "salon" and p["type"] not in ("text", "crowd") else 1.0) * s * 1.2
            if p.get("impact"):
                kk = R.clamp((t - p["_t"]) / 0.18); R.paste(area, img, x + dx, y + dy, pscale * (1 + 0.7 * (1 - R.ease_out(kk))), R.clamp(kk * 3))
            else:
                s_, a_ = R.pop(t, p["_t"], 0.3)
                fl = math.sin(t * 2.2 + x) * 4 if p["type"] in ("banknote", "thought", "bubble", "emoji") else 0
                R.paste(area, img, x + dx, y + fl + dy, pscale * s_, a_)
        if z > 1.002:
            cw, chh = int(area.width / z), int(area.height / z); ox, oy = (area.width - cw) // 2, int((area.height - chh) * 0.45)
            area = area.crop((ox, oy, ox + cw, oy + chh)).resize((area.width, area.height), Image.BILINEAR)
        if st == "papier":
            fr = Image.new("RGBA", (W, H), (0, 0, 0, 255)); fr.alpha_composite(area, (0, BAN_H))
            ban = self.cfg.get("banner")
            if ban:
                bimg = self.cached(("ban", tuple(ban)), lambda: self.banner_img(ban)); R.paste(fr, bimg, W // 2, BAN_H / 2 + 4, 0.72)
            cy = BAN_H + Ha * 0.5
        else:
            fr = area; cy = H * 0.52
        cur = None
        for tc, txt in self.caps:
            if t >= tc: cur = (tc, txt)
        if cur:
            im = self.caption(cur[1], st); s_, a_ = R.pop(t, cur[0], 0.12)
            sc_ = min(0.85, 1300 / im.width)
            R.paste(fr, im, W // 2, cy, sc_ * (0.9 + 0.1 * s_), a_)
        for t0, card in self.chapters:
            if t0 <= t < t0 + 1.8:
                a = R.clamp((t - t0) / 0.2) * R.clamp((t0 + 1.8 - t) / 0.3)
                R.paste(fr, card, W // 2, H // 2, 1.0 + 0.08 * (1 - R.ease_out(R.clamp((t - t0) / 0.3))), a)
        if self.cfg.get("hook") and R.HOOK_T0 <= t < R.HOOK_T1:
            hl = Image.new("RGBA", (R.W, R.H), (0, 0, 0, 0)); R.hook_overlay(hl, self.cfg, t, 760)
            bb = hl.getbbox()
            if bb: R.paste(fr, hl.crop(bb), W // 2 + (bb[0] + bb[2]) / 2 - R.W / 2, H // 2 + (bb[1] + bb[3]) / 2 - 760, 1.15)
        return fr.convert("RGB")


def make_thumb_wide(cfg, out):
    th = cfg["thumb"]; st = th.get("style", cfg.get("style", "papier")); TW, TH = 1280, 720
    bg, s = wide_bg(st, th.get("bg", "school" if st == "papier" else "living"), H)
    img = bg.resize((TW, TH), Image.LANCZOS)
    ov = Image.new("RGBA", (TW, TH), (0, 0, 0, 0)); ImageDraw.Draw(ov).rectangle([520, 0, TW, TH], fill=(0, 0, 0, 150))
    img.alpha_composite(ov.filter(ImageFilter.GaussianBlur(40)))
    def fit(txt, mx, sz):
        while R.font(R.F_BLACK, sz).getlength(txt) > mx and sz > 24: sz -= 2
        return R.font(R.F_BLACK, sz)
    chars = th.get("chars", [{"who": "kid", "face": "shock", "pose": "arms_up", "x": 540}])
    for i, c in enumerate(chars[:2]):
        p = E.person(st, c.get("who", "kid"), c.get("pose", "arms_up"), c.get("face", "shock"))
        sc = 640 / p.height * (1.0 if i == 0 else 0.85); p = p.resize((int(p.width * sc), int(p.height * sc)), Image.LANCZOS)
        img.alpha_composite(p, (int(250 + i * 200 - p.width / 2), TH - p.height + 20))
    x0 = 560; mx = TW - x0 - 40
    t1 = R.text_img(th["title1"], fit(th["title1"], mx, 104), (255, 255, 255), stroke=9, sfill=(10, 10, 10))
    em = R.emoji_img(th.get("emoji", "😳"), 92)
    t2 = R.text_img(th["title2"], fit(th["title2"], mx - em.width - 20, 120), (255, 210, 63), stroke=9, sfill=(10, 10, 10))
    y = 90; img.alpha_composite(t1, (x0, y)); y += t1.height + 6
    img.alpha_composite(t2, (x0, y)); img.alpha_composite(em, (x0 + t2.width + 16, y + (t2.height - em.height) // 2)); y += t2.height + 40
    d = ImageDraw.Draw(img)
    if th.get("banner"):
        bt = th["banner"]; fb = R.font(R.F_XB, 50)
        while fb.getlength(bt) > mx - 60 and fb.size > 24: fb = R.font(R.F_XB, fb.size - 2)
        tw = fb.getlength(bt); d.rounded_rectangle([x0, y, x0 + tw + 60, y + 86], 18, fill=(230, 50, 60)); d.text((x0 + 30, y + 16), bt, font=fb, fill=(255, 255, 255)); y += 116
    if th.get("bottom"):
        tb = R.text_img(th["bottom"], fit(th["bottom"], mx, 64), (255, 255, 255), stroke=7, sfill=(10, 10, 10)); img.alpha_composite(tb, (x0, y))
    img.convert("RGB").save(out, quality=92)


def sheet(v, dur, out):
    ts = list(np.linspace(0.5, dur - 1, 12)); s = Image.new("RGB", (480 * 4, 270 * 3))
    for i, x in enumerate(ts): s.paste(v.render(x).resize((480, 270)), ((i % 4) * 480, (i // 4) * 270))
    s.save(out, quality=85); print("OK", out)


def main():
    cmd = sys.argv[1]; cfg = json.load(open(sys.argv[2]))
    if cmd == "thumb": make_thumb_wide(cfg, sys.argv[3]); print("OK", sys.argv[3]); return
    if cmd == "demo":
        words = E.fake_words(sys.argv[4]); dur = words[-1]["end"] + 0.7
        sheet(WideEcole(cfg, words, dur), dur, sys.argv[3]); return
    voice, words, out = sys.argv[3], R.load_words(sys.argv[4]), sys.argv[5]
    dur = R._dur(voice) + 0.7
    v = WideEcole(cfg, words, dur); v.load_voice(voice)
    if cmd == "stills": sheet(v, dur, out); return
    E.build_audio(v, voice, "_mix.wav")
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-i", "_mix.wav", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                          "-shortest", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    n = int(dur * FPS)
    for i in range(n):
        p.stdin.write(v.render(i / FPS).tobytes())
        if i % 300 == 0: print(f"{i}/{n}", flush=True)
    p.stdin.close(); p.wait(); print(f"OK {out} ({dur:.1f} s)")


if __name__ == "__main__":
    main()
