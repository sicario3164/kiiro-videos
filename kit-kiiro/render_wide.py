"""Version HORIZONTALE 16:9 de render_rw.py (vidéos longues YouTube Psychologie du complot). Aucune barre de progression."""
import sys, os, json, math, random, subprocess, urllib.request, urllib.parse
from concurrent.futures import ProcessPoolExecutor
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1920, 1080, 30
FD = "/usr/share/fonts/opentype/inter/"
F_BLACK, F_BOLD, F_SEMI = FD + "InterDisplay-Black.otf", FD + "InterDisplay-Bold.otf", FD + "InterDisplay-SemiBold.otf"
WHITE, ACCENT, RED, GREY = (245, 245, 240), (255, 210, 63), (230, 57, 70), (150, 150, 160)
GAP = 0.35
TAIL = 1.0
HOOK_CY = 330
CAP_CY = 900
CAP_MAXW = 1400

MIN_TOTAL = 0
CLIP_LEN = 2.6
MAX_GAP = 0.22
CTA = {}
OUTRO_HOOKS = [
    {"dt": 0.0, "tag": "LA VÉRITÉ DANS LE MENSONGE", "text": "UN LIVRE ÉCRIT *POUR TOI*"},
    {"dt": "amazon", "tag": "DISPO SUR AMAZON", "text": "MOINS DE *10 €*"},
    {"dt": "lien", "tag": "", "text": "LIEN DANS *MA BIO*"},
]

def parse(text):
    toks, acc = [], False
    for raw in text.split(" "):
        w = raw
        if w.startswith("*"):
            acc = True; w = w[1:]
        end = "*" in w
        toks.append((w.replace("*", ""), acc))
        if end:
            acc = False
    return toks

def wrap(toks, font, maxw):
    space = font.getlength(" ")
    lines, cur, curw = [], [], 0
    for w, a in toks:
        ww = font.getlength(w)
        if cur and curw + space + ww > maxw:
            lines.append((cur, curw)); cur, curw = [], 0
        curw += (space if cur else 0) + ww
        cur.append((w, a, ww))
    if cur:
        lines.append((cur, curw))
    return lines, space

def shadowed(img, blur=12, alpha=0.75, dy=6):
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sh.putalpha(img.getchannel("A").filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * alpha)))
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.alpha_composite(sh, (0, dy)); out.alpha_composite(img)
    return out

def render_hook(h):
    text = h["text"]
    n = len(text.replace("*", ""))
    size = 120 if n <= 14 else 104 if n <= 24 else 88 if n <= 36 else 74
    font = ImageFont.truetype(F_BLACK, size)
    toks = []
    for w, a in parse(text):
        if a and toks and toks[-1][1]:
            toks[-1] = (toks[-1][0] + " " + w, True)
        else:
            toks.append((w, a))
    while True:
        lines, space = wrap(toks, font, 1500)
        if all(lw <= 1520 for _, lw in lines) or size <= 64:
            break
        size -= 8; font = ImageFont.truetype(F_BLACK, size)
    asc, desc = font.getmetrics()
    lh = int((asc + desc) * 1.02)
    tag_img = None
    if h.get("tag"):
        tf = ImageFont.truetype(F_BOLD, 40)
        ta, td = tf.getmetrics()
        tw = tf.getlength(h["tag"])
        tag_img = Image.new("RGBA", (int(tw + 56), ta + td + 30), (0, 0, 0, 0))
        d = ImageDraw.Draw(tag_img)
        d.rounded_rectangle([0, 0, tag_img.width - 1, tag_img.height - 1], radius=12, fill=RED + (255,))
        d.text((28, 15), h["tag"], font=tf, fill=WHITE)
    top = (tag_img.height + 30) if tag_img else 0
    img = Image.new("RGBA", (W, top + lh * len(lines) + 30), (0, 0, 0, 0))
    if tag_img:
        img.alpha_composite(tag_img, ((W - tag_img.width) // 2, 0))
    d = ImageDraw.Draw(img)
    for i, (ln, lw) in enumerate(lines):
        x, y = (W - lw) / 2, top + i * lh
        for w, a, ww in ln:
            if a:
                d.rectangle([x - 8, y + asc * 0.60, x + ww + 8, y + asc * 1.03], fill=RED + (170,))
            d.text((x, y), w, font=font, fill=ACCENT if a else WHITE)
            x += ww + space
    return shadowed(img, 14, 0.8)

CAP_FONT = ImageFont.truetype(F_BLACK, 66)

def render_caption(words, active):
    lines, space = wrap([(w, False) for w in words], CAP_FONT, CAP_MAXW)
    asc, desc = CAP_FONT.getmetrics()
    lh = int((asc + desc) * 1.1)
    img = Image.new("RGBA", (W, lh * len(lines) + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = 0
    for i, (ln, lw) in enumerate(lines):
        x, y = (W - lw) / 2, 10 + i * lh
        for w, _, ww in ln:
            col = ACCENT if k == active else WHITE
            d.text((x, y), w, font=CAP_FONT, fill=col, stroke_width=7, stroke_fill=(0, 0, 0))
            x += ww + space
            k += 1
    return shadowed(img, 10, 0.6, 4)

def load_words(path, offset):
    d = json.load(open(path))
    ws = d["words"] if isinstance(d, dict) else d
    out = []
    for w in ws:
        if w.get("type", "word") != "word":
            continue
        t = w["text"].strip()
        if not t:
            continue
        if all(c in ":;?!.,…«»" for c in t) and out:
            out[-1]["text"] += (" " + t if t in ":;?!»" else t)
            continue
        out.append({"text": t, "start": w["start"] + offset, "end": w["end"] + offset})
    return out

def make_chunks(words):
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        txt = " ".join(x["text"] for x in cur)
        if len(cur) >= 4 or len(txt) >= 24 or w["text"][-1] in ".?!…:,»":
            chunks.append(cur); cur = []
    if cur:
        chunks.append(cur)
    res = []
    for i, c in enumerate(chunks):
        start = c[0]["start"]
        nxt = chunks[i + 1][0]["start"] if i + 1 < len(chunks) else c[-1]["end"] + 0.6
        end = min(nxt, c[-1]["end"] + 0.6)
        res.append({"words": c, "start": start, "end": end})
    return res

def vignette():
    v = Image.new("L", (W, H), 0)
    ImageDraw.Draw(v).ellipse([-W * 0.3, -H * 0.15, W * 1.3, H * 1.15], fill=255)
    v = v.filter(ImageFilter.GaussianBlur(200))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.putalpha(v.point(lambda x: int((255 - x) * 0.45)))
    return out

UA = {"User-Agent": "curl/8.5.0"}

def http_get(url, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)

BANNED = ("church", "cross", "jesus", "christ", "god", "pray", "relig", "buddh", "temple", "mosque", "islam",
          "bible", "occult", "satan", "pentagram", "devil", "witch", "flag", "politic", "nude", "blood", "weapon", "gun",
          "cartoon", "animat", "character", "green screen", "chroma", "greenscreen", "2d", "illustration", "render", "3d")

HIT_CACHE = {}

def pixabay_hits(query):
    if query in HIT_CACHE:
        return HIT_CACHE[query]
    key = os.environ["PIXABAY_KEY"]
    url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode(
        {"key": key, "q": query, "per_page": 40, "safesearch": "true"})
    try:
        hits = json.load(http_get(url, 30)).get("hits", [])
    except Exception as e:
        print("pixabay error", query, e); hits = []
    if not hits and " " in query:
        hits_list = pixabay_hits(query.rsplit(" ", 1)[0])
        HIT_CACHE[query] = hits_list
        return hits_list
    hits = [h for h in hits if not any(b in h.get("tags", "").lower() for b in BANNED)]
    stop = ("looking", "night", "dark", "view", "close", "slow", "motion", "background", "aerial", "vintage", "old")
    stems = [w[:5] for w in query.lower().split() if len(w) >= 4 and w not in stop]
    tg = lambda h: h.get("tags", "").lower()
    rel_all = [h for h in hits if stems and all(st in tg(h) for st in stems)]
    rel_any = [h for h in hits if stems and any(st in tg(h) for st in stems)]
    hits = (rel_all if len(rel_all) >= 2 else rel_any if len(rel_any) >= 2 else hits)[:8]
    def portrait(h):
        m = h["videos"].get("medium") or {}
        return (m.get("height") or 0) > (m.get("width") or 1)
    hits.sort(key=lambda h: (portrait(h),))
    out = []
    for h in hits:
        files = [f for f in (h["videos"].get(k) or {} for k in ("large", "medium", "small")) if f.get("url")]
        def eff(f):
            return min(f.get("width") or 0, (f.get("height") or 0) * 16 / 9)
        good = sorted([f for f in files if eff(f) >= 1900], key=eff)
        f = good[0] if good else (sorted(files, key=eff, reverse=True)[0] if files else None)
        if f:
            thumb = (h["videos"].get("small") or {}).get("thumbnail") or (h["videos"].get("tiny") or {}).get("thumbnail") or ""
            out.append((h["id"], f["url"], thumb, h.get("tags", "")))
    HIT_CACHE[query] = out
    return out

def build_background(segments, work):
    used, parts, k = set(), [], 0
    for i, seg in enumerate(segments):
        a, b, qs = seg[0], seg[1], seg[2]
        pick = seg[3] if len(seg) > 3 else None
        dur = b - a
        if qs and qs[0] == "__CTA__":
            out = f"{work}/bg_{k:03d}.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", CTA["video"], "-t", f"{dur:.3f}", "-vf",
                            "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0c0c14,setsar=1,fps=30,tpad=stop_mode=clone:stop_duration=2", "-an", "-c:v", "libx264",
                            "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", out], check=True)
            parts.append(out); k += 1
            continue
        n = max(1, int(round(dur / CLIP_LEN)))
        cuts = [a + dur * j / n for j in range(n + 1)]
        pool = []
        for q in qs:
            pool += [x for x in pixabay_hits(q) if x[0] not in used and x not in pool]
        if pick is not None:
            first = pixabay_hits(qs[0])
            if isinstance(pick, int) and 0 <= pick < len(first) and first[pick][0] not in used:
                pool = [first[pick]] + [x for x in pool if x[0] != first[pick][0]]
        for j in range(n):
            d = cuts[j + 1] - cuts[j]
            out = f"{work}/bg_{k:03d}.mp4"
            src_url = None
            while pool and src_url is None:
                vid, u = pool.pop(0)[:2]
                if vid not in used:
                    used.add(vid); src_url = u
            if src_url:
                src = f"{work}/src_{k:03d}.mp4"
                try:
                    with http_get(src_url) as resp, open(src, "wb") as fh:
                        fh.write(resp.read())
                except Exception as e:
                    print("download error", e); src_url = None
            if src_url:
                xs = "(iw-ow)*t/%.3f" % d if k % 2 == 0 else "(iw-ow)*(1-t/%.3f)" % d
                vf = ("scale=2150:1210:force_original_aspect_ratio=increase:flags=lanczos,crop=2150:1210,setsar=1,fps=30,"
                      f"crop=1920:1080:x='{xs}':y='(ih-oh)/2',unsharp=5:5:0.6:5:5:0.0,eq=saturation=1.0:brightness=0.02")
                cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", src, "-t", f"{d:.3f}",
                       "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", out]
            else:
                prev = parts[-1] if parts else None
                if prev:
                    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", prev, "-t", f"{d:.3f}",
                           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out]
                else:
                    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x0c0c14:s=1920x1080:r=30",
                           "-t", f"{d:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out]
            subprocess.run(cmd, check=True)
            parts.append(out); k += 1
    with open(f"{work}/bg_list.txt", "w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", f"{work}/bg_list.txt",
                    "-c", "copy", f"{work}/bg.mp4"], check=True)
    print("clips:", len(parts))
    return f"{work}/bg.mp4"

def preview(hooks_p, words_p, out_jpg):
    """Contact sheet: for each shot, spoken words + query + 4 candidate thumbnails (0-3)."""
    spec = json.load(open(hooks_p))
    shots = spec.get("shots") or [{"t": h["t"], "q": h.get("bg", ""), "alt": h.get("alt", [])} for h in spec["hooks"]]
    ws = load_words(words_p, 0.0)
    rows = []
    fl = ImageFont.truetype(F_BOLD, 26); fs = ImageFont.truetype(F_SEMI, 22)
    for i, sh in enumerate(shots):
        t0 = sh["t"]; t1 = shots[i + 1]["t"] if i + 1 < len(shots) else 1e9
        said = " ".join(w["text"] for w in ws if t0 - 0.01 <= w["start"] < t1)
        cands = pixabay_hits(sh["q"])[:4]
        row = Image.new("RGB", (1400, 250), (20, 20, 26))
        d = ImageDraw.Draw(row)
        d.text((12, 8), f"#{i}  t={t0:.1f}s  q=\"{sh['q']}\"", font=fl, fill=(255, 210, 63))
        txt, line, y = said.split(), "", 44
        for w in txt:
            if fs.getlength(line + " " + w) > 330:
                d.text((12, y), line, font=fs, fill=(230, 230, 230)); y += 26; line = w
            else:
                line = (line + " " + w).strip()
        d.text((12, y), line, font=fs, fill=(230, 230, 230))
        for k, c in enumerate(cands):
            try:
                im = Image.open(http_get(c[2], 20)).convert("RGB") if c[2] else None
            except Exception:
                im = None
            x = 360 + k * 260
            if im:
                im.thumbnail((250, 190)); row.paste(im, (x, 44))
            d.text((x, 10), f"pick {k}: {c[3][:22]}", font=fs, fill=(150, 200, 255))
        rows.append(row)
    sheet = Image.new("RGB", (1400, 250 * max(1, len(rows))), (0, 0, 0))
    for i, r in enumerate(rows):
        sheet.paste(r, (0, 250 * i))
    sheet.save(out_jpg, quality=80)
    print("preview:", out_jpg, len(rows), "plans")

def tighten(main_a, words_path, work):
    """Shorten pauses longer than MAX_GAP and remap word timings."""
    d = json.load(open(words_path))
    ws = [w for w in (d["words"] if isinstance(d, dict) else d) if w.get("type", "word") == "word"]
    keep, shift, cur = [], [], 0.0
    removed = 0.0
    prev_end = 0.0
    for w in ws:
        gap = w["start"] - prev_end
        if gap > MAX_GAP:
            keep.append((cur, prev_end + MAX_GAP / 2))
            cur = w["start"] - MAX_GAP / 2
            removed += gap - MAX_GAP
        shift.append(removed)
        prev_end = max(prev_end, w["end"])
    keep.append((cur, None))
    for w, s in zip(ws, shift):
        w["start"] = round(w["start"] - s, 3); w["end"] = round(w["end"] - s, 3)
    parts = []
    for i, (a, b) in enumerate(keep):
        parts.append(f"[0:a]atrim=start={a:.3f}" + (f":end={b:.3f}" if b else "") + f",asetpts=PTS-STARTPTS[s{i}]")
    fc = ";".join(parts) + ";" + "".join(f"[s{i}]" for i in range(len(keep))) + f"concat=n={len(keep)}:v=0:a=1[a]"
    out_a = f"{work}/voice_tight.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", main_a, "-filter_complex", fc, "-map", "[a]",
                    "-ar", "44100", out_a], check=True)
    out_w = f"{work}/words_tight.json"
    json.dump({"words": ws}, open(out_w, "w"), ensure_ascii=False)
    print(f"tighten: removed {removed:.1f}s")
    return out_a, out_w

def whoosh(work):
    p = f"{work}/whoosh.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anoisesrc=d=0.45:c=pink:a=0.6:r=44100",
                    "-af", "highpass=f=400,lowpass=f=5000,afade=t=in:d=0.2,afade=t=out:st=0.2:d=0.25,volume=0.22", p], check=True)
    return p

def make_shade():
    a = Image.new("L", (W, H), 0)
    px = []
    for y in range(H):
        v = 0.12
        v += 0.26 * math.exp(-((y - HOOK_CY) / 170) ** 2)
        v += 0.30 * math.exp(-((y - CAP_CY) / 110) ** 2)
        v += 0.20 * max(0.0, 1 - y / 160)
        px.append(int(255 * min(0.92, v)))
    d = ImageDraw.Draw(a)
    for y, v in enumerate(px):
        d.line([(0, y), (W, y)], fill=v)
    img = Image.new("RGBA", (W, H), (6, 6, 12, 0))
    img.putalpha(a)
    return img

G = {}

def make_cta_shade():
    a = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(a)
    for y in range(H):
        v = 0.0
        v += 0.42 * math.exp(-((y - CAP_CY) / 110) ** 2)
        v += 0.30 * max(0.0, 1 - y / 300)
        d.line([(0, y), (W, y)], fill=int(255 * min(0.8, v)))
    img = Image.new("RGBA", (W, H), (6, 6, 12, 0))
    img.putalpha(a)
    return img

def make_cover(path, width=310):
    c = Image.open(path).convert("RGB")
    c = c.resize((width, int(c.height * width / c.width)), Image.LANCZOS)
    b = 8
    card = Image.new("RGBA", (c.width + 2 * b, c.height + 2 * b), (255, 255, 255, 255))
    card.paste(c, (b, b))
    pad = 40
    out = Image.new("RGBA", (card.width + 2 * pad, card.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("L", out.size, 0)
    ImageDraw.Draw(sh).rectangle([pad, pad + 10, pad + card.width, pad + card.height + 10], fill=180)
    out.putalpha(sh.filter(ImageFilter.GaussianBlur(16)))
    out.alpha_composite(card, (pad, pad))
    return out.rotate(-4, expand=True, resample=Image.BICUBIC)

def make_pill(text):
    tf = ImageFont.truetype(F_BLACK, 44)
    ta, td = tf.getmetrics()
    tw = tf.getlength(text)
    p = Image.new("RGBA", (int(tw + 52), ta + td + 28), (0, 0, 0, 0))
    d = ImageDraw.Draw(p)
    d.rounded_rectangle([0, 0, p.width - 1, p.height - 1], radius=14, fill=RED + (255,))
    d.text((26, 14), text, font=tf, fill=WHITE)
    return shadowed(p, 10, 0.6, 4)

def setup(hooks, chunks, total):
    G["SHADE"] = make_shade()
    G["VIG"] = vignette()
    tf = ImageFont.truetype(F_BLACK, 40)
    label = "Psychologie du complot"
    lw = tf.getlength(label)
    a, d_ = tf.getmetrics()
    bw, bh = int(lw + 80), a + d_ + 36
    box = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    bd = ImageDraw.Draw(box)
    bd.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=18, fill=(255, 255, 255, 255))
    bd.text((40, 18), label, font=tf, fill=(10, 10, 10))
    box = shadowed(box, 10, 0.45, 4)
    tl = Image.new("RGBA", (W, bh + 30), (0, 0, 0, 0))
    tl.alpha_composite(box, ((W - box.width) // 2, 0))
    G["TAG"] = tl if CTA.get("label") else Image.new("RGBA", (W, 2), (0, 0, 0, 0))
    G["hooks"] = hooks
    G["hook_imgs"] = [render_hook(h) for h in hooks]
    G["chunks"] = chunks
    G["cap_cache"] = {}
    G["total"] = total
    if CTA.get("cover"):
        G["CTA_SHADE"] = make_cta_shade()
        G["COVER"] = make_cover(CTA["cover"])
        G["PILLS"] = [(t, make_pill(s)) for t, s in CTA["pills"]]

def ease(t):
    t = max(0.0, min(1.0, t)); return 1 - (1 - t) ** 3

def draw_caption(img, t):
    for ci, c in enumerate(G["chunks"]):
        if c["start"] <= t < c["end"]:
            act = 0
            for k, w in enumerate(c["words"]):
                if w["start"] <= t:
                    act = k
            key = (ci, act)
            if key not in G["cap_cache"]:
                G["cap_cache"][key] = render_caption([w["text"] for w in c["words"]], act)
            cim = G["cap_cache"][key]
            q = ease((t - c["start"]) / 0.12)
            dy = int((1 - q) * 18)
            img.alpha_composite(cim, (0, int(CAP_CY - cim.height / 2) + dy))
            break

def frame_cta(t, bgframe):
    img = bgframe.convert("RGBA")
    img.alpha_composite(G["CTA_SHADE"])
    img.alpha_composite(G["TAG"], (0, 34))
    tc = CTA["cover_t"]
    if t >= tc:
        p = ease((t - tc) / 0.35)
        cv = G["COVER"]
        s = 0.6 + 0.4 * p
        im = cv if p >= 0.999 else cv.resize((max(1, int(cv.width * s)), max(1, int(cv.height * s))))
        if p < 0.999:
            im = im.copy(); im.putalpha(im.getchannel("A").point(lambda v: int(v * p)))
        cx, cy = 40 + cv.width // 2, 330 + cv.height // 2
        img.alpha_composite(im, (cx - im.width // 2, cy - im.height // 2))
        pill = None
        for pt, pim in G["PILLS"]:
            if pt <= t:
                pill = (pt, pim)
        if pill:
            q = ease((t - pill[0]) / 0.25)
            pim = pill[1]
            if q < 0.999:
                pim = pim.copy(); pim.putalpha(pim.getchannel("A").point(lambda v: int(v * q)))
            img.alpha_composite(pim, (70, 330 + cv.height - 10 + int((1 - q) * 14)))
    draw_caption(img, t)
    return img.convert("RGB")

def frame(t, bgframe):
    if CTA.get("cover") and t >= CTA["off"]:
        return frame_cta(t, bgframe)
    img = bgframe.convert("RGBA")
    img.alpha_composite(G["SHADE"])
    img.alpha_composite(G["TAG"], (0, 34))
    hi = max([i for i, h in enumerate(G["hooks"]) if h["t"] <= t] or [0])
    h, him = G["hooks"][hi], G["hook_imgs"][hi]
    p = ease((t - h["t"]) / 0.3) if t >= h["t"] else 1.0
    s = 0.86 + 0.14 * p
    im = him if p >= 0.999 else him.resize((int(him.width * s), int(him.height * s)))
    if p < 0.999:
        im = im.copy(); im.putalpha(im.getchannel("A").point(lambda v: int(v * p)))
    img.alpha_composite(im, ((W - im.width) // 2, int(HOOK_CY - im.height / 2)))
    for ci, c in enumerate(G["chunks"]):
        if c["start"] <= t < c["end"]:
            act = 0
            for k, w in enumerate(c["words"]):
                if w["start"] <= t:
                    act = k
            key = (ci, act)
            if key not in G["cap_cache"]:
                G["cap_cache"][key] = render_caption([w["text"] for w in c["words"]], act)
            cim = G["cap_cache"][key]
            q = ease((t - c["start"]) / 0.12)
            dy = int((1 - q) * 18)
            img.alpha_composite(cim, (0, int(CAP_CY - cim.height / 2) + dy))
            break
    img.alpha_composite(G["VIG"])
    # (barre de progression supprimée : interdite par l'utilisateur)
    return img.convert("RGB")

def bg_reader(bg, f0, n):
    return subprocess.Popen(["ffmpeg", "-loglevel", "error", "-ss", f"{f0 / FPS:.4f}", "-i", bg, "-frames:v", str(n),
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)

def read_frame(r, last):
    buf = r.stdout.read(W * H * 3)
    if len(buf) < W * H * 3:
        return last if last is not None else Image.new("RGB", (W, H), (12, 12, 20))
    return Image.frombytes("RGB", (W, H), buf)

def render_segment(args):
    idx, f0, f1, work, hooks, chunks, total, bg, cta = args
    CTA.clear(); CTA.update(cta)
    setup(hooks, chunks, total)
    r = bg_reader(bg, f0, f1 - f0); last = None
    tmp, final = f"{work}/seg_{idx:03d}.tmp.mp4", f"{work}/seg_{idx:03d}.mp4"
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                          "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                          "-pix_fmt", "yuv420p", tmp], stdin=subprocess.PIPE)
    for f in range(f0, f1):
        last = read_frame(r, last)
        p.stdin.write(frame(f / FPS, last).tobytes())
    r.wait()
    p.stdin.close()
    if p.wait() == 0:
        os.replace(tmp, final)
    return final

def duration(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).decode())

if __name__ == "__main__":
    if sys.argv[1] == "--preview":
        preview(sys.argv[2], sys.argv[3], sys.argv[4]); sys.exit(0)
    args = sys.argv[1:]
    label = "--label" in args
    if label:
        args.remove("--label")
    cta = None
    if "--cta" in args:
        i = args.index("--cta"); cta = args[i + 1:i + 4]; del args[i:i + 4]
    hooks_p, main_a, main_w, out = args[:4]
    out = os.path.abspath(out)
    work = out + ".parts"; os.makedirs(work, exist_ok=True)
    voice, words_p = tighten(main_a, main_w, work)
    dmain = duration(voice)
    words = load_words(words_p, 0.0)
    if cta:
        off = dmain + 0.35
        total = off + duration(cta[0]) + 0.25
        owords = load_words(cta[1], off)
        def find(word, default):
            for w in owords:
                if word in w["text"].lower():
                    return w["start"]
            return default
        CTA.update({"video": os.path.abspath(cta[0]), "cover": os.path.abspath(cta[2]), "off": off, "label": label,
                    "cover_t": find("livre", off + 4.8) - 0.15,
                    "pills": [(find("dossiers", off + 6.2) - 0.25, "13 DOSSIERS PROUVÉS"),
                              (find("amazon", off + 8.4) - 0.1, "DISPO SUR AMAZON"),
                              (find("euros", off + 9.6) - 0.35, "MOINS DE 10\u00a0€"),
                              (find("lien", off + 10.4) - 0.1, "LIEN DANS MA BIO")]})
    else:
        off = None
        total = max(MIN_TOTAL, dmain + 1.2)
        if label:
            CTA.update({"label": True, "off": 1e9})
    shift = json.load(open(main_w))
    spec = json.load(open(hooks_p))
    hooks = sorted(spec["hooks"], key=lambda h: h["t"])
    shots = sorted(spec.get("shots") or [], key=lambda x: x["t"])
    # remap hook times onto the tightened timeline using word starts
    orig = [w for w in (shift["words"] if isinstance(shift, dict) else shift) if w.get("type", "word") == "word"]
    tight = json.load(open(words_p))["words"]
    def remap(t):
        if t <= 0:
            return 0.0
        i = min(range(len(orig)), key=lambda k: abs(orig[k]["start"] - t))
        return tight[i]["start"]
    for h in hooks:
        h["t"] = round(remap(h["t"]), 3)
    for x in shots:
        x["t"] = round(remap(x["t"]), 3)
    chunks = make_chunks(words) + (make_chunks(owords) if cta else [])
    if cta:
        hooks = [h for h in hooks if h["t"] < off - 0.2]
    segs = []
    src_list = shots if shots else [{"t": h["t"], "q": h.get("bg") or "dark abstract", "alt": h.get("alt", [])} for h in hooks]
    for i, x in enumerate(src_list):
        a = 0.0 if i == 0 else x["t"]
        end = off if cta else total + 0.2
        b = src_list[i + 1]["t"] if i + 1 < len(src_list) else end
        if a >= end:
            continue
        segs.append((a, min(b, end), [x["q"]] + list(x.get("alt", [])), x.get("pick")))
    if cta:
        segs.append((off, total + 0.2, ["__CTA__"]))
    bg = build_background(segs, work)
    wh = whoosh(work)
    times = [h["t"] for h in hooks[1:]]
    inputs = ["-i", voice] + sum([["-i", wh] for _ in times], [])
    fc = "".join(f"[{i + 1}:a]adelay={int(max(0, t - 0.15) * 1000)}|{int(max(0, t - 0.15) * 1000)}[w{i}];" for i, t in enumerate(times))
    if cta:
        inputs += ["-i", cta[0]]
        ci = len(times) + 1
        fc += f"[0:a]aresample=44100,apad=whole_dur={off:.3f}[v0];[{ci}:a]aresample=44100[c];[v0][c]concat=n=2:v=0:a=1,apad=whole_dur={total:.3f}[v];[v]"
    else:
        fc += f"[0:a]apad=whole_dur={total:.3f}[v];[v]"
    fc += "".join(f"[w{i}]" for i in range(len(times))) + f"amix=inputs={len(times) + 1}:normalize=0:duration=first[a]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + inputs + ["-filter_complex", fc, "-map", "[a]", "-t", f"{total:.3f}",
                    "-c:a", "aac", "-b:a", "192k", f"{work}/audio.m4a"], check=True)
    setup(hooks, chunks, total)
    for i, h in enumerate(hooks):
        t = min(total - 0.1, (hooks[i + 1]["t"] if i + 1 < len(hooks) else total) - 0.4)
        t = max(t, h["t"] + 0.35)
        fr = int(t * FPS); r = bg_reader(bg, fr, 1)
        frame(t, read_frame(r, None)).save(f"{work}/still_{i:02d}.jpg", quality=85); r.wait()
    nframes = int(round(total * FPS))
    nseg = max(1, os.cpu_count() or 2)
    bounds = [round(nframes * i / nseg) for i in range(nseg + 1)]
    jobs = [(i, bounds[i], bounds[i + 1], work, hooks, chunks, total, bg, dict(CTA)) for i in range(nseg) if bounds[i + 1] > bounds[i]]
    with ProcessPoolExecutor() as ex:
        segs = list(ex.map(render_segment, jobs))
    with open(f"{work}/list.txt", "w") as f:
        for s in segs:
            f.write(f"file '{s}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", f"{work}/list.txt", "-c", "copy", f"{work}/video.mp4"], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{work}/video.mp4", "-i", f"{work}/audio.m4a", "-map", "0:v", "-map", "1:a",
                    "-c", "copy", "-shortest", "-movflags", "+faststart", f"{work}/final.mp4"], check=True)
    os.replace(f"{work}/final.mp4", out)
    print("OK", out, f"{total:.1f}s", f"voix {dmain:.1f}s", "stills:", work)
