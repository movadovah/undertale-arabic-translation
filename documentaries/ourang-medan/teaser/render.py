#!/usr/bin/env python3
"""Render the Ourang Medan cold-open teaser (no voice-over, Arabic captions).

Usage: python3 render.py <fonts_dir> <out_dir>
fonts_dir must contain NotoKufi.ttf and Amiri-1.000/Amiri-Regular.ttf.
Produces <out_dir>/ourang-medan-teaser.mp4 (1920x1080, 24 fps).
"""
import math, os, subprocess, sys, wave
from multiprocessing import Pool
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops

W, H, FPS = 1920, 1080, 24
DUR = 150.0
NFRAMES = int(DUR * FPS)
FONTS, OUT = sys.argv[1], sys.argv[2]
HORIZON = 640
RED = (200, 24, 32)
AMBER = (232, 160, 48)
BONE = (236, 230, 218)
GREEN = (60, 255, 120)

def font(name, size):
    path = os.path.join(FONTS, 'NotoKufi.ttf' if name == 'kufi' else 'Amiri-1.000/Amiri-Regular.ttf')
    f = ImageFont.truetype(path, size)
    if name == 'kufi':
        try: f.set_variation_by_axes([800])
        except Exception: pass
    return f

def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)

def clamp01(x): return min(max(x, 0.0), 1.0)

def fade(t, a, b, fin=0.4, fout=0.4):
    if t < a or t > b: return 0.0
    return min(clamp01((t - a) / fin), clamp01((b - t) / fout))

# ---------------------------------------------------------------- morse
CODE = {'S': '...', 'O': '---', 'I': '..', 'D': '-..', 'E': '.'}
def morse(text, start, unit):
    ev, t = [], start
    for ch in text:
        if ch == ' ':
            t += unit * 4; continue
        for s in CODE[ch]:
            d = unit if s == '.' else unit * 3
            ev.append((t, t + d)); t += d + unit
        t += unit * 2
    return ev, t

rng0 = np.random.default_rng(7)
def garble(start, end):
    ev, t = [], start
    while t < end:
        prog = (t - start) / (end - start)
        u = 0.07 + 0.05 * prog
        d = u * (1 if rng0.random() < 0.6 else 3) * (0.6 + rng0.random() * (0.8 + prog * 1.6))
        ev.append((t, t + d)); t += d + u * (0.5 + rng0.random() * (1 + 3 * prog))
    return ev

SOS1, e1 = morse('SOS', 1.0, 0.13)
SOS2, _ = morse('SOS', e1 + 0.9, 0.13)
SOS3, _ = morse('SOS', 36.3, 0.11)
GARB = garble(47.0, 54.0)
IDIE, IDIE_END = morse('I DIE', 60.8, 0.16)
LAST_DOT = [(149.0, 149.12)]
INTRO_PULSES = SOS1 + SOS2

def key_on(evs, t):
    return any(a <= t < b for a, b in evs)

# ---------------------------------------------------------------- captions
CAPS = [
    (10.0, 15.0, 'في مكانٍ ما وسط الظلام، رجلٌ ينقر على مفتاحٍ نحاسي.'),
    (15.5, 21.0, 'لا يتكلم. الرسائل هنا تسافر إيقاعًا: نقاطٌ وشَرَطات.'),
    (21.5, 28.0, 'لغةٌ من النقرات تعبر مئات الكيلومترات من الماء الأسود في لحظة.'),
    (29.0, 35.3, 'إنه يرسل الحروف الثلاثة التي يترك من أجلها كل عامل لاسلكي كل شيء.'),
    (41.0, 46.3, 'ثم يرسل موقعه… ثم يخبر العالم بما حدث على متن سفينته.'),
    (47.0, 53.5, 'وبعد مقطعٍ طويل من إشارةٍ لم تعد تعني شيئًا…'),
    (54.0, 59.0, '…تصل كلمتان أخيرتان.'),
    (71.0, 73.8, 'ثم هواءٌ ميت.'),
    (93.0, 98.7, 'نداء استغاثة ينقطع في منتصف الجملة.'),
    (99.0, 105.5, 'فريق إنقاذ يجد كل رجلٍ على متن السفينة ميتًا… بلا جرحٍ واحد.'),
    (106.0, 111.0, 'وجوهٌ متجمدة. كلبٌ نفق وهو يزمجر. حريق. انفجار.'),
    (111.5, 117.3, 'وبعد ذلك… لا شيء. لا حطام. لا مالك. لا تحقيق.'),
    (128.0, 134.0, 'هذه قصة «أورانغ ميدان»… سفينةٌ أرسلت واحدة من أكثر الرسائل رعبًا في تاريخ البحار.'),
    (134.5, 139.0, 'ثم اختفت عن وجه الأرض.'),
    (139.5, 144.0, 'أو ربما… سفينةٌ لم توجد أصلًا.'),
    (144.5, 148.3, 'الليلة سنعرف أيّهما.'),
]
LIGHTNING = [12.0, 25.5, 44.0, 57.6]
MONTAGE_T0, MONTAGE_STEP = 74.0, 2.6
MONTAGE_WORDS = ['صمت', 'موت', 'زمجرة', 'برد', 'دخان', 'نار', 'اختفاء']

# ---------------------------------------------------------------- assets (built per worker)
A = {}
def build_assets():
    rng = np.random.default_rng(1)
    # sky + water base
    y = np.linspace(0, 1, HORIZON)[:, None]
    top, hor = np.array([3, 6, 14]), np.array([16, 32, 52])
    sky = (top + (hor - top) * y ** 1.6)[:, None, :].repeat(W, 1)
    water = np.zeros((H - HORIZON, W, 3)) + np.array([2, 5, 10])
    A['base'] = np.concatenate([sky, water], 0).astype(np.float32)
    # fog layers
    fogs = []
    for i, (sc, al) in enumerate([(220, 0.20), (140, 0.16), (90, 0.12)]):
        small = rng.random((max(2, H // sc + 2), (2 * W) // sc + 2))
        im = Image.fromarray((small * 255).astype(np.uint8)).resize((2 * W, H), Image.BICUBIC)
        im = im.filter(ImageFilter.GaussianBlur(sc / 3))
        a = np.asarray(im, np.float32) / 255.0
        a = np.clip((a - 0.35) * 1.8, 0, 1) * al
        band = np.exp(-((np.arange(H) - (HORIZON - 40 + i * 90)) / (260 + i * 60)) ** 2)[:, None]
        fogs.append((a * band).astype(np.float32))
    A['fog'] = fogs
    # water glints
    g = Image.new('L', (2 * W, H - HORIZON), 0)
    d = ImageDraw.Draw(g)
    for _ in range(2600):
        yy = rng.random() ** 1.7 * (H - HORIZON)
        ln = 6 + (yy / (H - HORIZON)) * 90 * rng.random()
        xx = rng.random() * 2 * W
        d.line([(xx, yy), (xx + ln, yy)], fill=int(25 + 70 * rng.random()), width=1 + int(yy / 220))
    A['glint'] = np.asarray(g.filter(ImageFilter.GaussianBlur(1.2)), np.float32) / 255.0
    # ship silhouette (RGBA, 1000x420, waterline at y=330)
    s = Image.new('L', (1000, 420), 0)
    d = ImageDraw.Draw(s)
    d.polygon([(40, 250), (960, 230), (920, 330), (110, 335)], fill=255)          # hull
    d.rectangle([520, 150, 700, 245], fill=255)                                     # bridge house
    d.rectangle([560, 110, 670, 152], fill=255)                                     # wheelhouse
    d.polygon([(735, 70), (790, 70), (800, 240), (725, 240)], fill=255)             # funnel
    d.rectangle([150, 205, 260, 248], fill=255); d.rectangle([840, 190, 930, 236], fill=255)
    for x0, top_y in [(330, 20), (880, 60)]:
        d.line([(x0, top_y), (x0, 240)], fill=255, width=7)
        d.line([(x0 - 60, top_y + 60), (x0 + 60, top_y + 60)], fill=255, width=5)
    d.line([(330, 20), (880, 60)], fill=255, width=2)
    d.line([(330, 20), (60, 245)], fill=255, width=2); d.line([(880, 60), (950, 232)], fill=255, width=2)
    for x0 in range(540, 700, 34): d.rectangle([x0, 168, x0 + 14, 182], fill=0)   # dark windows
    A['ship'] = s
    # lightning bolts
    bolts = []
    for k in range(4):
        b = Image.new('L', (W, HORIZON), 0); d = ImageDraw.Draw(b)
        x, yy = 300 + k * 420 + rng.random() * 200, 0
        pts = [(x, yy)]
        while yy < HORIZON - 120:
            yy += 30 + rng.random() * 50; x += (rng.random() - 0.5) * 110; pts.append((x, yy))
        d.line(pts, fill=255, width=4)
        for j in range(2, len(pts) - 2, 3):
            bx, by = pts[j]; br = [(bx, by)]
            for _ in range(3):
                bx += (rng.random() - 0.3) * 80; by += 30 + rng.random() * 30; br.append((bx, by))
            d.line(br, fill=180, width=2)
        bolts.append(np.asarray(b.filter(ImageFilter.GaussianBlur(2)), np.float32) / 255.0)
    A['bolts'] = bolts
    # vignette + grain
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    A['vig'] = np.clip(1.0 - 0.55 * (r - 0.55).clip(0) ** 1.3, 0.25, 1)[:, :, None].astype(np.float32)
    A['grain'] = [rng.normal(0, 7, (H, W, 1)).astype(np.float32) for _ in range(6)]
    # caption band
    band = np.clip((np.arange(H) - 780) / 300, 0, 1) ** 1.5 * 0.75
    A['capband'] = band[:, None, None].astype(np.float32)
    # fonts + caption images
    A['cap_font'] = font('amiri', 58)
    A['kufi_big'] = font('kufi', 150)
    A['kufi_mid'] = font('kufi', 64)
    A['mono'] = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf', 120)
    A['mono_small'] = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 34)
    A['caps'] = [(a, b, text_img(txt, A['cap_font'], BONE, shadow=True)) for a, b, txt in CAPS]
    # title
    tf = font('kufi', 118)
    A['title'] = text_img('سفينة الأشباح في المضيق', tf, BONE)
    tm = np.asarray(A['title'].split()[3])
    ys, xs = np.nonzero(tm > 140)
    idx = rng.choice(len(xs), size=min(3200, len(xs)), replace=False)
    tw, th = A['title'].size
    A['tpts'] = np.stack([xs[idx] + (W - tw) / 2, ys[idx] + 400 - th / 2], 1).astype(np.float32)
    ang = rng.random(len(idx)) * 2 * np.pi; rad = 300 + rng.random(len(idx)) * 900
    A['tsrc'] = np.stack([W / 2 + np.cos(ang) * rad, H / 2 + np.sin(ang) * rad * 0.6], 1).astype(np.float32)
    A['tdelay'] = (rng.random(len(idx)) * 0.35).astype(np.float32)
    sf = font('kufi', 54)
    A['sub_red'] = text_img('الأسطورة', sf, RED)
    A['sub_slash'] = text_img('/', sf, (120, 120, 120))
    A['sub_amb'] = text_img('السجلّ', sf, AMBER)
    A['words'] = [text_img(w, A['kufi_big'], BONE) for w in MONTAGE_WORDS]
    A['sos_txt'] = text_img('S . O . S', ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf', 150), RED)
    A['ar_idie'] = text_img('أنا… أموت', font('amiri', 84), BONE, shadow=True)

def text_img(txt, f, color, shadow=False):
    tmp = Image.new('L', (10, 10)); d = ImageDraw.Draw(tmp)
    bb = d.textbbox((0, 0), txt, font=f, direction='rtl', language='ar')
    w, h = bb[2] - bb[0] + 40, bb[3] - bb[1] + 40
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    if shadow:
        sh = Image.new('RGBA', (w, h), (0, 0, 0, 0)); ds = ImageDraw.Draw(sh)
        ds.text((20 - bb[0], 20 - bb[1]), txt, font=f, fill=(0, 0, 0, 230), direction='rtl', language='ar')
        im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(6)))
        d = ImageDraw.Draw(im)
    d.text((20 - bb[0], 20 - bb[1]), txt, font=f, fill=color + (255,), direction='rtl', language='ar')
    return im

def paste_center(img, layer, cx, cy, alpha=1.0, scale=1.0):
    if alpha <= 0: return
    L = layer
    if scale != 1.0:
        L = L.resize((max(1, int(L.width * scale)), max(1, int(L.height * scale))), Image.LANCZOS)
    if alpha < 1.0:
        L = L.copy(); L.putalpha(L.split()[3].point(lambda v: int(v * alpha)))
    img.alpha_composite(L, (int(cx - L.width / 2), int(cy - L.height / 2)))

# ---------------------------------------------------------------- scenes
def lightning_level(t):
    lv, which = 0.0, -1
    for i, lt in enumerate(LIGHTNING):
        dt = t - lt
        if 0 <= dt < 0.6:
            v = math.exp(-dt * 9) + (0.6 * math.exp(-(dt - 0.18) * 14) if dt > 0.18 else 0)
            if v > lv: lv, which = v, i
    return min(lv, 1.0), which

def sea(t, ship_scale, ship_x, sink=0.0, fire=0.0):
    f = A['base'].copy()
    lv, which = lightning_level(t)
    # water glints
    gl = A['glint']; off = int(t * 18) % W
    g = gl[:, off:off + W]
    f[HORIZON:] += g[:, :, None] * np.array([70, 95, 130], np.float32) * (0.35 + 1.8 * lv)
    # fog
    for i, fg in enumerate(A['fog']):
        o = int(t * (8 + i * 9)) % W
        f += fg[:, o:o + W, None] * np.array([150, 170, 190], np.float32) * (1 + 1.5 * lv)
    # lightning sky + bolt
    if lv > 0:
        skyw = np.linspace(1, 0.25, HORIZON)[:, None, None]
        f[:HORIZON] += skyw * np.array([150, 170, 210], np.float32) * lv
        if which >= 0 and lv > 0.35:
            f[:HORIZON] += A['bolts'][which][:, :, None] * 255 * lv
    if fire > 0:
        yy, xx = np.ogrid[0:H, 0:W]
        cx, cy = ship_x + 120 * ship_scale, HORIZON - 30
        r = np.sqrt(((xx - cx) / 520.0) ** 2 + ((yy - cy) / 300.0) ** 2)
        fl = fire * (0.85 + 0.15 * math.sin(t * 23) * math.sin(t * 7))
        f += (np.exp(-r * r * 2.2) * fl)[:, :, None] * np.array([255, 90, 20], np.float32)
    img = Image.fromarray(np.clip(f, 0, 255).astype(np.uint8)).convert('RGBA')
    # ship
    s = A['ship']
    sw, sh = int(s.width * ship_scale), int(s.height * ship_scale)
    sm = s.resize((sw, sh), Image.BILINEAR)
    if sink > 0: sm = sm.rotate(-14 * sink, resample=Image.BILINEAR, expand=False)
    bob = math.sin(t * 0.9) * 4 * ship_scale
    top = int(HORIZON + 18 - 330 * ship_scale + bob + sink * 360 * ship_scale)
    m = Image.new('L', (W, H), 0); m.paste(sm, (int(ship_x - sw / 2), top))
    mk = np.asarray(m, np.float32) / 255.0
    mk[HORIZON + 16:] = 0  # waterline clip
    col = np.array([1, 2, 4], np.float32) + np.array([30, 34, 44], np.float32) * lv
    arr = np.asarray(img.convert('RGB'), np.float32)
    arr = arr * (1 - mk[:, :, None]) + col * mk[:, :, None]
    if fire > 0:  # fire light on the stern
        arr += (mk[:, :, None] * fire * 0.45) * np.array([255, 80, 20], np.float32) * \
               np.clip(1 - np.abs(np.arange(W) - (ship_x - 120 * ship_scale)) / (300 * ship_scale), 0, 1)[None, :, None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert('RGBA')

def scene_intro(t):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    d = ImageDraw.Draw(img)
    for a, b in INTRO_PULSES:
        if a - 0.02 <= t < b + 0.35:
            k = 1.0 if t < b else math.exp(-(t - b) * 9)
            dash = (b - a) > 0.2
            w = 150 if dash else 46
            glow = Image.new('RGBA', (W, H), (0, 0, 0, 0)); g = ImageDraw.Draw(glow)
            g.rounded_rectangle([W / 2 - w / 2, H / 2 - 23, W / 2 + w / 2, H / 2 + 23], 23, fill=(255, 40, 40, int(255 * k)))
            img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(18)))
            img.alpha_composite(glow)
    # snap-zoom into sea at 8.0-9.0
    if t >= 8.0:
        p = ease((t - 8.0) / 1.0)
        s = sea(t, 0.62, 1180)
        s = s.resize((int(W * (3 - 2 * p)), int(H * (3 - 2 * p))), Image.BILINEAR)
        cx, cy = s.width / 2, s.height / 2
        s = s.crop((int(cx - W / 2), int(cy - H / 2), int(cx + W / 2), int(cy + H / 2)))
        img = Image.blend(img, s, p)
    return img

def scene_sea(t):
    p = clamp01((t - 9) / 51)
    img = sea(t, 0.62 + 0.28 * ease(p), 1180 - 120 * p)
    if 36.0 <= t < 40.5:  # S.O.S slam
        a = fade(t, 36.0, 40.5, 0.15, 0.5)
        paste_center(img, A['sos_txt'], W / 2, 330, a, 1.0 + 0.4 * (1 - ease((t - 36.0) / 0.25)))
    return img

def scope(t):
    img = Image.new('RGBA', (W, H), (2, 10, 5, 255))
    d = ImageDraw.Draw(img)
    for x in range(0, W, 96): d.line([(x, 120), (x, 760)], fill=(10, 45, 22), width=1)
    for y in range(120, 761, 80): d.line([(0, y), (W, y)], fill=(10, 45, 22), width=1)
    d.line([(0, 440), (W, 440)], fill=(14, 70, 32), width=2)
    # trace: last 3 s of key state, scrolling right-to-left
    flat = t > IDIE_END + 0.3
    pts = []
    for i in range(0, W + 1, 4):
        tt = t - (W - i) / W * 3.0
        on = key_on(IDIE, tt)
        yv = 440 + (math.sin(i * 0.9) * 150 if on else (math.sin(i * 0.05 + t * 3) * 3 if not flat else 0))
        pts.append((i, yv))
    tr = Image.new('RGBA', (W, H), (0, 0, 0, 0)); dt = ImageDraw.Draw(tr)
    dt.line(pts, fill=GREEN + (255,), width=3)
    img.alpha_composite(tr.filter(ImageFilter.GaussianBlur(10)))
    img.alpha_composite(tr)
    # decoded letters
    letters, shown = 'I DIE', ''
    ends = []
    k = 0
    for ch in letters:
        if ch == ' ': ends.append(None); continue
        n = len(CODE[ch]); ends.append(IDIE[k + n - 1][1]); k += n
    for ch, e in zip(letters, ends):
        if e is None: shown += '   ' if shown else ''; continue
        if t >= e: shown += ch + ' '
    ghost = 1.0 if t < 70 else max(0.25, 1 - (t - 70) * 0.25)
    if shown:
        d.text((W / 2, 880), shown.strip(), font=A['mono'], fill=tuple(int(c * ghost) for c in RED), anchor='mm')
    d.text((60, 70), '500 kHz  ·  CW', font=A['mono_small'], fill=(30, 140, 70))
    if t >= 65.0:
        paste_center(img, A['ar_idie'], W / 2, 1000, fade(t, 65.0, 70.5, 0.6, 0.8))
    return img

# montage icons --------------------------------------------------------
def icon(k, lt):
    im = Image.new('RGBA', (W, H), (0, 0, 0, 255)); d = ImageDraw.Draw(im)
    cx, cy = W / 2, 430
    if k == 0:  # morse key + slumped hand
        d.rectangle([cx - 300, cy + 120, cx + 300, cy + 160], fill=BONE)
        d.polygon([(cx - 220, cy + 110), (cx + 200, cy + 60), (cx + 210, cy + 85), (cx - 210, cy + 125)], fill=BONE)
        d.ellipse([cx + 170, cy + 20, cx + 260, cy + 80], fill=RED)
        d.polygon([(cx + 120, cy - 40), (cx + 330, cy - 10), (cx + 300, cy + 40), (cx + 160, cy + 50), (cx + 60, cy + 10)], fill=(150, 145, 140))
    elif k == 1:  # figure on the floor
        d.line([(cx - 500, cy + 170), (cx + 500, cy + 170)], fill=(80, 80, 80), width=4)
        d.ellipse([cx - 360, cy + 70, cx - 270, cy + 160], fill=BONE)
        d.rounded_rectangle([cx - 270, cy + 90, cx + 120, cy + 165], 30, fill=BONE)
        d.line([(cx - 200, cy + 100), (cx - 120, cy - 40)], fill=BONE, width=26)
        d.line([(cx + 110, cy + 120), (cx + 330, cy + 150)], fill=BONE, width=28)
        d.ellipse([cx - 340, cy + 95, cx - 322, cy + 113], fill=(0, 0, 0))
    elif k == 2:  # snarl
        d.pieslice([cx - 360, cy - 200, cx + 360, cy + 220], 200, 340, fill=(40, 10, 12))
        teeth_u = [(cx - 300 + i * 50, cy - 40) for i in range(13)]
        for i in range(12):
            x0 = cx - 300 + i * 50
            d.polygon([(x0, cy - 60), (x0 + 50, cy - 60), (x0 + 25, cy + 10 + (25 if i in (2, 9) else 0))], fill=BONE)
            d.polygon([(x0, cy + 120), (x0 + 50, cy + 120), (x0 + 25, cy + 50 - (25 if i in (3, 8) else 0))], fill=BONE)
        d.line([(cx - 330, cy - 70), (cx + 330, cy - 70)], fill=RED, width=10)
        d.line([(cx - 330, cy + 130), (cx + 330, cy + 130)], fill=RED, width=10)
    elif k == 3:  # thermometer dropping + frost
        d.rounded_rectangle([cx - 40, cy - 260, cx + 40, cy + 160], 40, outline=BONE, width=8)
        d.ellipse([cx - 80, cy + 120, cx + 80, cy + 280], outline=BONE, width=8)
        lvl = cy - 200 + 330 * ease(lt / 2.0)
        d.rectangle([cx - 18, lvl, cx + 18, cy + 170], fill=RED); d.ellipse([cx - 60, cy + 140, cx + 60, cy + 260], fill=RED)
        rr = np.random.default_rng(3)
        for _ in range(int(60 * ease(lt / 2.2))):
            ex, ey = (rr.random() < 0.5) * W, rr.random() * H
            ang = rr.random() * 6.28
            for s in range(4):
                nx, ny = ex + math.cos(ang) * 120, ey + math.sin(ang) * 120
                d.line([(ex, ey), (nx, ny)], fill=(150, 190, 220), width=2); ex, ey = nx, ny; ang += rr.random() - 0.5
    elif k == 4:  # smoke from hatch
        d.rectangle([cx - 300, cy + 150, cx + 300, cy + 210], fill=(90, 90, 90))
        d.rectangle([cx - 260, cy + 120, cx + 260, cy + 150], fill=BONE)
        sm = Image.new('L', (W, H), 0); ds = ImageDraw.Draw(sm)
        for i in range(14):
            ph = (lt * 0.5 + i / 14) % 1
            r = 40 + 150 * ph
            ds.ellipse([cx - r + math.sin(i * 1.7 + lt) * 70 * ph, cy + 110 - 520 * ph - r, cx + r + math.sin(i * 1.7 + lt) * 70 * ph, cy + 110 - 520 * ph + r], fill=int(200 * (1 - ph)))
        sm = sm.filter(ImageFilter.GaussianBlur(25))
        im.paste(Image.new("RGBA", (W, H), (150, 150, 158, 255)), (0, 0), sm)
    elif k == 5:  # fireball
        fb = Image.new('RGBA', (W, H), (0, 0, 0, 0)); df = ImageDraw.Draw(fb)
        p = ease(lt / 1.2)
        for r, c in [(420, (120, 10, 10)), (320, (220, 50, 10)), (220, (255, 140, 30)), (110, (255, 230, 160))]:
            R = r * (0.3 + 0.8 * p)
            df.ellipse([cx - R, cy - R, cx + R, cy + R], fill=c + (230,))
        im.alpha_composite(fb.filter(ImageFilter.GaussianBlur(30))); im.alpha_composite(fb.filter(ImageFilter.GaussianBlur(6)))
    elif k == 6:  # bow sinking
        bw = Image.new('RGBA', (900, 900), (0, 0, 0, 0)); db = ImageDraw.Draw(bw)
        db.polygon([(450, 60), (620, 760), (280, 760)], fill=BONE)
        db.line([(450, 60), (450, 760)], fill=(170, 165, 160), width=6)
        bw = bw.rotate(-25, resample=Image.BICUBIC)
        y = cy - 260 + 640 * ease(lt / 2.4)
        im.alpha_composite(bw, (int(cx - 450), int(y - 450)))
        d = ImageDraw.Draw(im); d.rectangle([0, cy + 180, W, H], fill=(0, 0, 0)); d.line([(0, cy + 180), (W, cy + 180)], fill=(60, 70, 90), width=3)
    return im

def scene_montage(t):
    k = min(int((t - MONTAGE_T0) / MONTAGE_STEP), 6)
    lt = t - MONTAGE_T0 - k * MONTAGE_STEP
    img = icon(k, lt)
    sc = 1.0 + 0.6 * (1 - ease(lt / 0.22))
    paste_center(img, A['words'][k], W / 2, 860, fade(lt, 0, MONTAGE_STEP, 0.05, 0.25), sc)
    if lt < 0.25:  # shake
        dx, dy = int((np.random.default_rng(int(t * 100)).random() - 0.5) * 30), int((np.random.default_rng(int(t * 77)).random() - 0.5) * 30)
        img = ImageChops.offset(img, dx, dy)
    return img

def scene_aftermath(t):
    fire = fade(t, 102.0, 113.0, 2.0, 3.5)
    sink = ease((t - 107.0) / 10.0)
    img = sea(t, 0.8, 1060, sink=sink, fire=fire)
    if t > 117.0:
        k = clamp01((t - 117.0) / 1.0)
        img = Image.blend(img, Image.new('RGBA', (W, H), (0, 0, 0, 255)), k)
    return img

def scene_title(t):
    img = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    p = (t - 118.0) / 5.5
    if t < 124.5:
        q = np.clip((p - A['tdelay']) / (1 - 0.35), 0, 1)
        q = q * q * (3 - 2 * q)
        swirl = (1 - q) * 2.2
        src = A['tsrc'] - [W / 2, H / 2]
        rot = np.stack([src[:, 0] * np.cos(swirl) - src[:, 1] * np.sin(swirl), src[:, 0] * np.sin(swirl) + src[:, 1] * np.cos(swirl)], 1) + [W / 2, H / 2]
        pos = rot * (1 - q[:, None]) + A['tpts'] * q[:, None]
        lay = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
        a = int(255 * fade(t, 118.0, 125.0, 0.6, 0.6))
        for x, y in pos: d.ellipse([x - 2.5, y - 2.5, x + 2.5, y + 2.5], fill=RED + (a,))
        img.alpha_composite(lay.filter(ImageFilter.GaussianBlur(4))); img.alpha_composite(lay)
    if t >= 123.6:
        a = clamp01((t - 123.6) / 0.8) * (1 - clamp01((t - 148.3) / 1.2))
        glow = A['title'].filter(ImageFilter.GaussianBlur(14))
        paste_center(img, glow, W / 2, 400, a * 0.8)
        paste_center(img, A['title'], W / 2, 400, a)
    if t >= 125.8:
        a = clamp01((t - 125.8) / 0.6) * (1 - clamp01((t - 148.3) / 1.2))
        sep = 140 * (1 - ease((t - 125.8) / 0.8)) + 40
        paste_center(img, A['sub_red'], W / 2 + sep + A['sub_red'].width / 2 - 20, 560, a)
        paste_center(img, A['sub_slash'], W / 2, 560, a)
        paste_center(img, A['sub_amb'], W / 2 - sep - A['sub_amb'].width / 2 + 20, 560, a)
    if 149.0 <= t < 149.5:
        k = 1.0 if t < 149.12 else math.exp(-(t - 149.12) * 9)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([W / 2 - 23, H / 2 + 300 - 23, W / 2 + 23, H / 2 + 300 + 23], 23, fill=(int(255 * k), int(40 * k), int(40 * k)))
    return img

def render(i):
    t = i / FPS
    if t < 9.0: img = scene_intro(t)
    elif t < 59.6: img = scene_sea(t)
    elif t < 74.0:
        img = scope(t)
        if t < 60.1: img = Image.blend(Image.new('RGBA', (W, H), (255, 255, 255, 255)), img, clamp01((t - 59.6) / 0.5))
    elif t < 92.2: img = scene_montage(t)
    elif t < 118.0: img = scene_aftermath(t)
    else: img = scene_title(t)
    # captions
    capa = [(a, b, c) for a, b, c in A['caps'] if a <= t <= b]
    if capa or (92 < t < 118) or (9 < t < 60):
        arr = np.asarray(img.convert('RGB'), np.float32)
        if capa: arr *= (1 - A['capband'] * max(fade(t, a, b) for a, b, _ in capa))
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert('RGBA')
    for a, b, c in capa:
        paste_center(img, c, W / 2, 960, fade(t, a, b))
    arr = np.asarray(img.convert('RGB'), np.float32)
    arr = arr * A['vig'] + A['grain'][i % 6]
    fo = clamp01(t / 0.3) * (1 - clamp01((t - 149.6) / 0.4)) if t > 148 else 1.0
    return np.clip(arr * fo, 0, 255).astype(np.uint8)

def chunk(args):
    ci, a, b = args
    build_assets()
    path = os.path.join(OUT, f'part{ci}.mp4')
    p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS),
                          '-i', '-', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', path], stdin=subprocess.PIPE)
    for i in range(a, b):
        p.stdin.write(render(i).tobytes())
    p.stdin.close(); p.wait()
    return path

# ---------------------------------------------------------------- audio
SR = 48000
def audio(path):
    n = int(DUR * SR); t = np.arange(n) / SR
    rng = np.random.default_rng(5)
    out = np.zeros(n)
    def env(a, b, fi=1.0, fo=1.0):
        return np.clip((t - a) / fi, 0, 1) * np.clip((b - t) / fo, 0, 1)
    def lowpass(x, k):
        y = np.copy(x)
        for _ in range(3):
            y = np.convolve(y, np.ones(k) / k, 'same')
        return y
    noise = rng.normal(0, 1, n)
    rumble = lowpass(noise, 400) * 6
    hiss = noise - lowpass(noise, 6)
    drone = (np.sin(2 * np.pi * 41 * t) + 0.7 * np.sin(2 * np.pi * 55.3 * t + np.sin(t * 0.3))) * (0.6 + 0.4 * np.sin(t * 0.21))
    sea_env = env(8.0, 59.6, 1.5, 0.05) + env(92.2, 118.5, 1.0, 1.5)
    out += (0.10 * drone + 0.25 * rumble) * (sea_env + 0.35 * env(118, 148.5, 2, 1.5))
    out += 0.035 * hiss * sea_env  # rain
    out += 0.06 * drone * env(74, 92.2, 0.1, 0.1)
    def beep(evs, f=680, amp=0.22):
        for a, b in evs:
            i0, i1 = int(a * SR), int(b * SR)
            seg = np.arange(i1 - i0) / SR
            e = np.minimum(1, np.minimum(seg / 0.004, (b - a - seg) / 0.004))
            out[i0:i1] += amp * np.sin(2 * np.pi * f * seg) * e
    beep(INTRO_PULSES); beep(SOS3, amp=0.16); beep(GARB, f=690, amp=0.12); beep(IDIE, f=700, amp=0.2); beep(LAST_DOT, amp=0.18)
    # static during morse scenes
    out += 0.03 * hiss * (env(46.5, 54.5, 0.5, 0.5) + env(60.0, IDIE_END + 0.3, 0.2, 0.05))
    # screech building into first lightning cut
    seg = env(5.0, 8.0, 3.0, 0.02)
    out += 0.07 * np.sin(2 * np.pi * (900 * t + 300 * t * t)) * seg * (0.6 + 0.4 * np.sin(t * 60))
    # lightning: crack + boom
    for lt in LIGHTNING:
        i0 = int(lt * SR); L = int(2.5 * SR)
        s = np.arange(L) / SR
        out[i0:i0 + L] += (0.5 * hiss[:L] * np.exp(-s * 12) + 0.9 * rumble[:L] * np.exp(-s * 1.4) * 2)[:len(out[i0:i0 + L])]
    # montage hits
    for k in range(7):
        a = MONTAGE_T0 + k * MONTAGE_STEP; i0 = int(a * SR); L = int(1.2 * SR); s = np.arange(L) / SR
        out[i0:i0 + L] += 0.7 * np.sin(2 * np.pi * (60 * s - 20 * s * s)) * np.exp(-s * 4) + 0.3 * hiss[:L] * np.exp(-s * 40)
    # explosion in the aftermath (sync with fire peak)
    i0 = int(108.0 * SR); L = int(5 * SR); s = np.arange(L) / SR
    out[i0:i0 + L] += 1.2 * rumble[:L] * 3 * np.exp(-s * 0.9) + 0.4 * hiss[:L] * np.exp(-s * 5)
    out += 0.05 * np.sin(2 * np.pi * 3200 * t) * env(108.3, 113, 0.05, 3)  # tinnitus ring
    # horn at title
    s = t - 123.8; m = (s > 0) & (s < 6)
    horn = (np.sign(np.sin(2 * np.pi * 73 * s)) * 0.5 + np.sin(2 * np.pi * 110 * s)) * np.clip(s / 0.3, 0, 1) * np.clip((6 - s) / 2.5, 0, 1)
    out += 0.18 * lowpass(horn * m, 12)
    # piano-like motif under the closing captions
    for k, (nt, f) in enumerate([(128, 220), (129.2, 261.6), (130.4, 329.6), (132.4, 293.7), (136, 220), (137.2, 261.6), (138.4, 246.9), (141, 196), (145, 220)]):
        s = t - nt; m = s > 0
        out += 0.09 * m * np.exp(-np.clip(s, 0, None) * 1.6) * (np.sin(2 * np.pi * f * s) + 0.4 * np.sin(4 * np.pi * f * s))
    # simple reverb
    rev = np.copy(out)
    for d, g in [(0.031, 0.35), (0.047, 0.3), (0.071, 0.25), (0.113, 0.2), (0.173, 0.15)]:
        k = int(d * SR); rev[k:] += g * out[:-k]
    out = rev
    out *= np.clip((DUR - 0.05 - t) / 0.3, 0, 1)
    out = np.tanh(out * 1.1) * 0.9
    st = (np.stack([out, out], 1) * 32767).astype(np.int16)
    with wave.open(path, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(st.tobytes())

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    if len(sys.argv) > 3:  # preview stills: render.py fonts out t1 t2 ...
        build_assets()
        for ts in sys.argv[3:]:
            Image.fromarray(render(int(float(ts) * FPS))).save(os.path.join(OUT, f'still_{ts}.png'))
        sys.exit()
    audio(os.path.join(OUT, 'audio.wav'))
    nproc = os.cpu_count() or 4
    bounds = np.linspace(0, NFRAMES, nproc + 1).astype(int)
    with Pool(nproc) as pool:
        parts = pool.map(chunk, [(i, bounds[i], bounds[i + 1]) for i in range(nproc)])
    lst = os.path.join(OUT, 'parts.txt')
    open(lst, 'w').write(''.join(f"file '{p}'\n" for p in parts))
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-i', os.path.join(OUT, 'audio.wav'),
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart',
                    os.path.join(OUT, 'ourang-medan-teaser.mp4')], check=True)
    for p in parts: os.remove(p)
    print('done')
