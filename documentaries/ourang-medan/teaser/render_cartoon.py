#!/usr/bin/env python3
"""Ourang Medan: cartoon-style cold open (hand-drawn look, Arabic captions, no voice-over).

Original characters: round white heads, thick black outlines, gloved hands,
expressive eyes, flat colour backgrounds with spotlights, and "boiling"
hand-drawn lines.

Usage:
  python3 render_cartoon.py <fonts_dir> <out_dir>            # full video
  python3 render_cartoon.py <fonts_dir> <out_dir> 10 30 ...  # preview stills (seconds)
"""
import math, os, subprocess, sys, wave
from multiprocessing import Pool
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
S = 2                       # supersampling factor
RFPS, OFPS = 12, 24         # drawn "on twos", delivered at 24 fps
DUR = 160.0
FONTS, OUT = sys.argv[1], sys.argv[2]

INK = (24, 20, 22)
WHITE = (250, 248, 242)
RED = (214, 40, 46)
AMBER = (236, 168, 52)
NAVY = (36, 48, 84)
GOLD = (232, 186, 70)
SKIN_SHADOW = (214, 210, 204)

def clamp01(x): return min(max(x, 0.0), 1.0)
def ease(x):
    x = clamp01(x); return x * x * (3 - 2 * x)
def fade(t, a, b, fi=0.35, fo=0.35):
    if t < a or t > b: return 0.0
    return min(clamp01((t - a) / fi), clamp01((b - t) / fo))

_fonts = {}
def font(name, size):
    key = (name, size)
    if key not in _fonts:
        p = {'kufi': 'NotoKufi.ttf', 'amiri': 'Amiri-1.000/Amiri-Regular.ttf', 'amirib': 'Amiri-1.000/Amiri-Bold.ttf'}[name]
        f = ImageFont.truetype(os.path.join(FONTS, p), size)
        if name == 'kufi':
            try: f.set_variation_by_axes([800])
            except Exception: pass
        _fonts[key] = f
    return _fonts[key]

# ======================================================================== pen
class Pen:
    """Draws in 1920x1080 coordinates onto an S-times supersampled canvas, with hand-drawn wobble."""
    def __init__(self, img, boil):
        self.img = img; self.d = ImageDraw.Draw(img); self.boil = boil; self.sid = 0
    def _rng(self):
        self.sid += 1
        return np.random.default_rng((self.boil * 7919 + self.sid * 104729) % (2 ** 32))
    def _j(self, pts, amp):
        r = self._rng()
        return [((x + (r.random() - .5) * amp) * S, (y + (r.random() - .5) * amp) * S) for x, y in pts]
    def poly(self, pts, fill=None, ow=5, oc=INK, amp=2.2, closed=True):
        P = self._j(pts, amp)
        if fill is not None and len(P) > 2: self.d.polygon(P, fill=fill)
        if ow:
            Q = P + [P[0]] if closed else P
            self.d.line(Q, fill=oc, width=int(ow * S), joint='curve')
            for x, y in ([P[0]] if not closed else []) + ([P[-1]] if not closed else []):
                r = ow * S / 2; self.d.ellipse([x - r, y - r, x + r, y + r], fill=oc)
    def ellipse(self, cx, cy, rx, ry, fill=None, ow=5, oc=INK, amp=1.6, a0=0, a1=360, n=44):
        pts = [(cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a)))
               for a in np.linspace(a0, a1, n, endpoint=(a1 - a0) < 360)]
        self.poly(pts, fill, ow, oc, amp, closed=(a1 - a0) >= 360)
    def arc(self, cx, cy, rx, ry, a0, a1, w=5, col=INK, amp=1.2):
        pts = [(cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a))) for a in np.linspace(a0, a1, 16)]
        self.poly(pts, None, w, col, amp, closed=False)
    def line(self, pts, w=5, col=INK, amp=1.5):
        self.poly(pts, None, w, col, amp, closed=False)
    def limb(self, pts, w, col, ow=5):
        P = self._j(pts, 1.5)
        for width, c in ((w + 2 * ow, INK), (w, col)):
            self.d.line(P, fill=c, width=int(width * S), joint='curve')
            for x, y in (P[0], P[-1]):
                r = width * S / 2; self.d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    def dot(self, x, y, r, col=INK):
        self.d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=col)
    def rect(self, x0, y0, x1, y1, fill=None, ow=5, oc=INK, amp=2.0):
        self.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], fill, ow, oc, amp)
    def text(self, x, y, txt, name='kufi', size=40, col=INK, anchor='mm', stroke=0, sc=WHITE):
        f = font(name, int(size * S))
        self.d.text((x * S, y * S), txt, font=f, fill=col, anchor=anchor, direction='rtl', language='ar',
                    stroke_width=int(stroke * S), stroke_fill=sc)

def new_canvas(color):
    return Image.new('RGB', (W * S, H * S), color)

def radial_bg(c_out, c_in, cx=0.5, cy=0.45, rad=0.8):
    yy, xx = np.mgrid[0:H // 4, 0:W // 4]
    r = np.sqrt(((xx / (W / 4) - cx) * 1.6) ** 2 + (yy / (H / 4) - cy) ** 2) / rad
    k = np.clip(1 - r, 0, 1)[:, :, None] ** 1.4
    a = np.array(c_out) * (1 - k) + np.array(c_in) * k
    return Image.fromarray(a.astype(np.uint8)).resize((W * S, H * S), Image.BICUBIC)

def spotlight_bg(base, beam, cx=0.5):
    img = Image.new('RGB', (W * S, H * S), base)
    m = Image.new('L', (W * S, H * S), 0); d = ImageDraw.Draw(m)
    d.polygon([((cx - .06) * W * S, 0), ((cx + .06) * W * S, 0), ((cx + .22) * W * S, H * S * .86), ((cx - .22) * W * S, H * S * .86)], fill=150)
    d.ellipse([(cx - .24) * W * S, H * S * .78, (cx + .24) * W * S, H * S * .94], fill=170)
    img.paste(Image.new('RGB', img.size, beam), (0, 0), m.filter(ImageFilter.GaussianBlur(40 * S)))
    return img

# ======================================================================== characters
def face(p, hx, hy, s, expr, look=(0, 0), shake=0.0, t=0.0):
    ex = 21 * s; ey = -6 * s
    lx, ly = look
    jx = (math.sin(t * 61) * shake * 3 * s) if shake else 0
    if expr == 'dead':
        for sx in (-1, 1):
            p.arc(hx + sx * ex, hy + ey, 11 * s, 7 * s, 10, 170, 4 * s ** .5)
        p.ellipse(hx, hy + 26 * s, 8 * s, 9 * s, fill=(60, 40, 44), ow=3)
        return
    big = expr in ('scared', 'terrified')
    erx, ery = (15 * s, 18 * s) if big else (11 * s, 12 * s)
    for sx in (-1, 1):
        cx = hx + sx * ex + jx
        if expr in ('angry', 'determined'):
            p.ellipse(cx, hy + ey + 2 * s, erx, ery * .75, fill=WHITE, ow=3.5)
        else:
            p.ellipse(cx, hy + ey, erx, ery, fill=WHITE, ow=3.5)
        pr = (3 if big else 4.5) * s
        p.dot(cx + lx * erx * .45, hy + ey + ly * ery * .45 + (1 if big else 0), pr)
        # brows
        if expr in ('angry', 'determined'):
            tilt = 9 if expr == 'angry' else 5
            p.line([(cx - sx * 16 * s, hy + ey - 20 * s), (cx + sx * 14 * s, hy + ey - (20 - tilt) * s)], 5 * s ** .6)
        elif expr in ('scared', 'terrified', 'worried'):
            p.line([(cx - sx * 13 * s, hy + ey - 23 * s), (cx + sx * 13 * s, hy + ey - 31 * s)], 4.5 * s ** .6)
        else:
            p.line([(cx - 11 * s, hy + ey - 21 * s), (cx + 11 * s, hy + ey - 22 * s)], 4 * s ** .6)
    my = hy + 27 * s
    if expr in ('scared', 'terrified'):
        w2, h2 = (22 * s, 11 * s) if expr == 'scared' else (26 * s, 15 * s)
        pts = [(hx - w2, my - h2 * .3), (hx - w2 * .4, my - h2 * .7), (hx + w2 * .4, my - h2 * .5), (hx + w2, my - h2 * .2),
               (hx + w2 * .8, my + h2 * .7), (hx - w2 * .7, my + h2 * .8)]
        p.poly(pts, fill=WHITE, ow=4)
        for k in range(1, 5):
            xk = hx - w2 + 2 * w2 * k / 5
            p.line([(xk, my - h2 * .55), (xk, my + h2 * .7)], 2.5)
        p.line([(hx - w2 * .9, my + h2 * .1), (hx + w2 * .9, my + h2 * .05)], 2.5)
    elif expr == 'angry':
        p.arc(hx, my + 10 * s, 15 * s, 9 * s, 200, 340, 4.5)
    elif expr == 'worried':
        p.line([(hx - 14 * s, my + 2 * s), (hx - 5 * s, my - 3 * s), (hx + 5 * s, my + 3 * s), (hx + 14 * s, my - 1 * s)], 4)
    elif expr == 'determined':
        p.line([(hx - 13 * s, my), (hx + 13 * s, my - 2 * s)], 4.5)
    else:
        p.arc(hx, my - 6 * s, 12 * s, 7 * s, 20, 160, 4)

def sweat(p, x, y, s, n=1):
    for k in range(n):
        xx, yy = x + k * 16 * s, y + k * 20 * s
        p.poly([(xx, yy - 14 * s), (xx + 8 * s, yy + 3 * s), (xx, yy + 10 * s), (xx - 8 * s, yy + 3 * s)], fill=(120, 190, 240), ow=3)

def hat(p, hx, hy, s, kind):
    if kind == 'headphones':
        p.arc(hx, hy - 4 * s, 60 * s, 62 * s, 195, 345, 9 * s ** .5, (60, 60, 66))
        for sx in (-1, 1):
            p.ellipse(hx + sx * 58 * s, hy + 2 * s, 13 * s, 22 * s, fill=(70, 70, 78), ow=4)
    elif kind == 'captain':
        p.poly([(hx - 58 * s, hy - 40 * s), (hx + 58 * s, hy - 40 * s), (hx + 52 * s, hy - 62 * s), (hx - 52 * s, hy - 62 * s)], fill=NAVY, ow=4.5)
        p.ellipse(hx, hy - 68 * s, 64 * s, 16 * s, fill=WHITE, ow=4.5)
        p.ellipse(hx, hy - 36 * s, 52 * s, 11 * s, fill=INK, ow=3, a0=0, a1=180)
        p.ellipse(hx, hy - 52 * s, 10 * s, 9 * s, fill=GOLD, ow=3)
    elif kind == 'sailor':
        p.poly([(hx - 46 * s, hy - 44 * s), (hx - 38 * s, hy - 78 * s), (hx + 38 * s, hy - 78 * s), (hx + 46 * s, hy - 44 * s)], fill=WHITE, ow=4.5)
        p.ellipse(hx, hy - 44 * s, 58 * s, 13 * s, fill=WHITE, ow=4.5)
    elif kind == 'beanie':
        p.ellipse(hx, hy - 40 * s, 57 * s, 40 * s, fill=(46, 74, 110), ow=4.5, a0=180, a1=360)
        p.rect(hx - 59 * s, hy - 46 * s, hx + 59 * s, hy - 30 * s, fill=(36, 60, 92), ow=4.5)
    elif kind == 'fedora':
        p.ellipse(hx, hy - 42 * s, 92 * s, 17 * s, fill=(112, 82, 58), ow=4.5)
        p.poly([(hx - 50 * s, hy - 46 * s), (hx - 44 * s, hy - 96 * s), (hx, hy - 84 * s), (hx + 44 * s, hy - 96 * s), (hx + 50 * s, hy - 46 * s)], fill=(128, 94, 66), ow=4.5)
        p.rect(hx - 50 * s, hy - 62 * s, hx + 50 * s, hy - 48 * s, fill=(40, 30, 26), ow=3)

def arm_end(x, y, s, sx, ang, bend):
    sh = (x + sx * 46 * s, y + 16 * s); a1 = math.radians(ang) * sx
    el = (sh[0] + math.sin(a1) * 62 * s, sh[1] + math.cos(a1) * 62 * s); a2 = a1 + math.radians(bend) * sx
    return (el[0] + math.sin(a2) * 58 * s, el[1] + math.cos(a2) * 58 * s)

def morse_key(p, hx, hy, down, k=1.0):
    p.rect(hx - 150 * k, hy + 14 * k, hx + 60 * k, hy + 44 * k, fill=(150, 110, 60), ow=4)
    dy = (10 if down else 0) * k
    p.poly([(hx - 130 * k, hy + 8 * k), (hx + 10 * k, hy - 8 * k + dy), (hx + 12 * k, hy + 6 * k + dy), (hx - 128 * k, hy + 20 * k)], fill=GOLD, ow=4)
    p.ellipse(hx, hy - 6 * k + dy, 16 * k, 10 * k, fill=INK, ow=2)

def person(p, x, y, s, spec, t=0.0):
    """(x, y) = top of the torso (neck). spec keys: coat, hat, expr, la, ra (arm angles, 0=down, +=outward),
    lb, rb (elbow bends), legs (bool), mustache, beard, glasses, look, shake, sweat, collar, head_dy, tilt."""
    coat = spec.get('coat', (90, 90, 96))
    la, ra = spec.get('la', 10), spec.get('ra', 10)
    lb, rb = spec.get('lb', 0), spec.get('rb', 0)
    legs = spec.get('legs', True)
    if legs:
        for sx in (-1, 1):
            p.limb([(x + sx * 22 * s, y + 140 * s), (x + sx * 26 * s, y + 245 * s)], 26 * s, spec.get('pants', (60, 60, 66)))
            p.ellipse(x + sx * 34 * s, y + 252 * s, 26 * s, 12 * s, fill=INK, ow=3)
    def arm(sx, ang, bend):
        sh = (x + sx * 46 * s, y + 16 * s)
        a1 = math.radians(ang) * sx
        el = (sh[0] + math.sin(a1) * 62 * s, sh[1] + math.cos(a1) * 62 * s)
        a2 = a1 + math.radians(bend) * sx
        hd = (el[0] + math.sin(a2) * 58 * s, el[1] + math.cos(a2) * 58 * s)
        p.limb([sh, el, hd], 24 * s, coat)
        p.ellipse(hd[0], hd[1], 16 * s, 15 * s, fill=INK, ow=2)
        return hd
    # torso
    p.poly([(x - 50 * s, y + 6 * s), (x + 50 * s, y + 6 * s), (x + 46 * s, y + 150 * s), (x - 46 * s, y + 150 * s)], fill=coat, ow=5)
    col = spec.get('collar', 'v')
    if col == 'v':
        p.poly([(x - 18 * s, y + 6 * s), (x + 18 * s, y + 6 * s), (x, y + 48 * s)], fill=WHITE, ow=3.5)
    elif col == 'sailor':
        p.poly([(x - 30 * s, y + 6 * s), (x + 30 * s, y + 6 * s), (x, y + 56 * s)], fill=WHITE, ow=3.5)
        p.poly([(x - 9 * s, y + 40 * s), (x + 9 * s, y + 40 * s), (x, y + 62 * s)], fill=RED, ow=3)
    for k in range(spec.get('buttons', 3)):
        p.dot(x, y + (66 + k * 26) * s, 5 * s, spec.get('btn', GOLD))
    hands = (arm(-1, la, lb), arm(1, ra, rb))
    # head
    hx, hy = x + spec.get('head_dx', 0) * s, y - 58 * s + spec.get('head_dy', 0) * s
    p.ellipse(hx, hy, 56 * s, 58 * s, fill=spec.get('skin', WHITE), ow=5.5)
    face(p, hx, hy, s, spec.get('expr', 'neutral'), spec.get('look', (0, 0)), spec.get('shake', 0), t)
    if spec.get('mustache'):
        mc = spec.get('mcol', (70, 60, 56))
        p.poly([(hx - 26 * s, hy + 18 * s), (hx, hy + 12 * s), (hx + 26 * s, hy + 18 * s), (hx + 20 * s, hy + 24 * s), (hx, hy + 19 * s), (hx - 20 * s, hy + 24 * s)], fill=mc, ow=3)
    if spec.get('beard'):
        p.poly([(hx - 46 * s, hy + 14 * s), (hx - 30 * s, hy + 48 * s), (hx, hy + 60 * s), (hx + 30 * s, hy + 48 * s), (hx + 46 * s, hy + 14 * s),
                (hx + 22 * s, hy + 36 * s), (hx - 22 * s, hy + 36 * s)], fill=(170, 166, 160), ow=3.5)
    if spec.get('glasses'):
        for sx in (-1, 1): p.ellipse(hx + sx * 21 * s, hy - 6 * s, 17 * s, 16 * s, ow=3.5)
        p.line([(hx - 4 * s, hy - 8 * s), (hx + 4 * s, hy - 8 * s)], 3)
    if spec.get('hat'): hat(p, hx, hy, s, spec['hat'])
    if spec.get('sweat'): sweat(p, hx + 52 * s, hy - 30 * s, s * .9, spec['sweat'])
    return hands, (hx, hy)

def dog(p, x, y, s, snarl=True, lit=True):
    c = (196, 150, 104)
    for dx in (-60, -30, 40, 66):
        p.limb([(x + dx * s, y + 10 * s), (x + dx * s, y + 70 * s)], 18 * s, c)
    p.ellipse(x, y, 92 * s, 44 * s, fill=c, ow=5)
    p.line([(x - 88 * s, y - 10 * s), (x - 130 * s, y - 52 * s)], 7)
    hx, hy = x + 104 * s, y - 40 * s
    p.ellipse(hx, hy, 46 * s, 40 * s, fill=c, ow=5)
    p.poly([(hx - 30 * s, hy - 30 * s), (hx - 50 * s, hy - 82 * s), (hx - 6 * s, hy - 40 * s)], fill=(150, 108, 74), ow=4)
    p.poly([(hx + 40 * s, hy - 6 * s), (hx + 92 * s, hy + 4 * s), (hx + 90 * s, hy + 32 * s), (hx + 34 * s, hy + 30 * s)], fill=c, ow=5)
    p.dot(hx + 92 * s, hy + 6 * s, 8 * s)
    if snarl:
        p.rect(hx + 40 * s, hy + 14 * s, hx + 88 * s, hy + 30 * s, fill=WHITE, ow=3)
        for k in range(5): p.line([(hx + (44 + k * 10) * s, hy + 14 * s), (hx + (49 + k * 10) * s, hy + 24 * s), (hx + (54 + k * 10) * s, hy + 14 * s)], 2.5)
        p.line([(hx + 8 * s, hy - 22 * s), (hx + 30 * s, hy - 12 * s)], 5)
    p.arc(hx + 14 * s, hy - 8 * s, 9 * s, 5 * s, 10, 170, 4)

def ship(p, x, y, s, eyes=False, col=(30, 30, 36), oc=INK):
    p.poly([(x - 230 * s, y - 40 * s), (x + 240 * s, y - 52 * s), (x + 200 * s, y + 30 * s), (x - 200 * s, y + 34 * s)], fill=col, ow=6, oc=oc)
    p.rect(x - 40 * s, y - 120 * s, x + 90 * s, y - 44 * s, fill=col, ow=5, oc=oc)
    p.poly([(x + 120 * s, y - 170 * s), (x + 156 * s, y - 170 * s), (x + 164 * s, y - 48 * s), (x + 112 * s, y - 48 * s)], fill=col, ow=5, oc=oc)
    p.line([(x - 140 * s, y - 200 * s), (x - 140 * s, y - 44 * s)], 6, oc)
    p.line([(x - 185 * s, y - 160 * s), (x - 95 * s, y - 160 * s)], 5, oc)
    if eyes:
        for sx, rot in ((-1, 1), (1, -1)):
            ex = x + sx * 70 * s - 20 * s
            p.poly([(ex - 42 * s, y - 20 * s + rot * 10 * s), (ex + 42 * s, y - 20 * s - rot * 10 * s), (ex + 30 * s, y + 6 * s), (ex - 30 * s, y + 6 * s)], fill=WHITE, ow=0)

# ======================================================================== morse + timeline
CODE = {'S': '...', 'O': '---', 'I': '..', 'D': '-..', 'E': '.'}
def morse(text, start, unit):
    ev, t = [], start
    for ch in text:
        if ch == ' ': t += unit * 4; continue
        for sym in CODE[ch]:
            d = unit if sym == '.' else 3 * unit; ev.append((t, t + d)); t += d + unit
        t += 2 * unit
    return ev, t
_r = np.random.default_rng(11)
def garble(a, b):
    ev, t = [], a
    while t < b:
        pr = (t - a) / (b - a); u = .07 + .05 * pr
        d = u * (1 if _r.random() < .6 else 3) * (.6 + _r.random() * (.8 + 1.6 * pr)); ev.append((t, t + d))
        t += d + u * (.5 + _r.random() * (1 + 3 * pr))
    return ev
SOS0, e0 = morse('SOS', 0.8, 0.13)
SOS0b, _ = morse('SOS', e0 + 0.5, 0.12)
SOS1, _ = morse('SOS', 18.6, 0.13)
GARB = garble(61.0, 67.0)
IDIE, IDIE_END = morse('I DIE', 67.4, 0.12)
LAST = [(159.0, 159.12)]
def key_on(evs, t): return any(a <= t < b for a, b in evs)

CAPS = [
    (8.0, 12.5, 'في مكانٍ ما وسط الظلام، رجلٌ ينقر على مفتاحٍ نحاسي.'),
    (13.0, 17.6, 'لا يتكلم… الرسائل هنا تسافر نقاطًا وشَرَطات.'),
    (18.2, 23.6, 'ويرسل الحروف الثلاثة التي يترك لها كل عامل لاسلكي كل شيء.'),
    (25.0, 30.4, 'مضيق مَلَقا… أواخر الأربعينيات. ممرٌّ ضيق بين سومطرة والملايو.'),
    (31.0, 35.9, 'محطات لاسلكي تلتقط استغاثة من سفينة اسمها «أورانغ ميدان».'),
    (36.4, 41.6, 'حتى تاريخ الحادثة مختلفٌ عليه… تذكّر هذا جيدًا.'),
    (42.6, 46.6, 'هذا نص الرسالة كما تتناقله الروايات:'),
    (52.6, 59.3, 'لاحظ: لا يقول «حريق» ولا «هجوم» ولا «غرق»… فقط: الجميع موتى.'),
    (73.4, 75.7, 'ثم… صمت.'),
    (77.0, 81.9, 'أقرب سفينة كانت أمريكية: «سيلفر ستار». غيّرت مسارها فورًا.'),
    (82.4, 87.4, 'قراصنة؟ ألغام؟ وباء؟ لا أحد يعرف ما ينتظرهم هناك.'),
    (88.0, 91.6, 'وعند الفجر… وجدوها.'),
    (93.0, 97.8, 'لا دم. لا رصاص. لا أثر لعراك.'),
    (98.4, 103.4, 'كل رجلٍ على متن السفينة… ميت.'),
    (104.0, 108.4, 'حتى الكلب… مات وهو يكشّر عن أنيابه.'),
    (109.0, 111.8, 'وعامل اللاسلكي… يده ما زالت على المفتاح.'),
    (113.0, 117.9, 'لكن حين بحث المحققون عن السفينة… لم يجدوا شيئًا.'),
    (118.4, 123.4, 'لا سجل. لا مالك. لا طاقم. لا تحقيق.'),
    (124.0, 129.4, 'فقط قصة… تكبر مع كل من يرويها.'),
    (140.0, 144.9, 'سفينةٌ أرسلت أكثر الرسائل رعبًا في تاريخ البحار…'),
    (145.4, 149.8, 'أم سفينةٌ لم توجد أصلًا؟'),
    (151.0, 155.0, 'الليلة… سنعرف.'),
]
CUTS = [7.0, 24.0, 42.0, 60.0, 76.0, 92.0, 112.0, 130.0]   # scene boundaries (whip transitions)
LIGHTNING = [10.8, 19.6]

# ======================================================================== scenes
def sc_intro(t, b):
    img = new_canvas((6, 6, 8)); d = ImageDraw.Draw(img)
    for a, e in SOS0 + SOS0b:
        if a <= t < e + .3:
            k = 1 if t < e else math.exp(-(t - e) * 9)
            w = 150 if e - a > .2 else 46
            g = Image.new('L', img.size, 0); dg = ImageDraw.Draw(g)
            dg.rounded_rectangle([(W / 2 - w / 2) * S, (H / 2 - 23) * S, (W / 2 + w / 2) * S, (H / 2 + 23) * S], 23 * S, fill=int(255 * k))
            img.paste(Image.new('RGB', img.size, (255, 40, 50)), (0, 0), g.filter(ImageFilter.GaussianBlur(14 * S)))
            img.paste(Image.new('RGB', img.size, (255, 70, 80)), (0, 0), g)
    return img, (0.5, 0.5, 1.0)

def sc_radio(t, b):
    img = radial_bg((26, 24, 30), (122, 92, 60), cx=.42, cy=.35, rad=.75)
    p = Pen(img, b)
    # porthole with storm
    lt = max([math.exp(-(t - L) * 8) if t >= L else 0 for L in LIGHTNING] + [0])
    p.ellipse(1500, 300, 150, 150, fill=(int(18 + 160 * lt), int(28 + 170 * lt), int(52 + 190 * lt)), ow=14, oc=(70, 58, 50))
    p.ellipse(1500, 300, 150, 150, ow=5)
    for k in range(6):
        a = math.radians(k * 60); p.dot(1500 + 150 * math.cos(a), 300 + 150 * math.sin(a), 8, (150, 130, 100))
    for k in range(9):  # rain streaks
        xx = 1400 + ((k * 37 + t * 300) % 200); yy = 200 + ((k * 53 + t * 900) % 200)
        p.line([(xx, yy), (xx - 10, yy + 26)], 2.5, (150, 170, 200))
    if lt > .4: p.line([(1470, 160), (1450, 250), (1490, 260), (1460, 380)], 5, (255, 255, 240))
    # wall shelf + calendar
    p.rect(180, 170, 420, 330, fill=(232, 222, 196), ow=5)
    p.text(300, 210, 'تقويم', 'kufi', 30); p.text(300, 275, '١٩٤٧ ؟', 'kufi', 44, RED)
    # desk & radio
    p.rect(0, 740, 1920, 1080, fill=(118, 78, 46), ow=6)
    p.line([(0, 790), (1920, 790)], 4, (90, 58, 34))
    p.rect(980, 440, 1440, 745, fill=(74, 78, 70), ow=6)
    for k, xx in enumerate((1060, 1160, 1260)):
        p.ellipse(xx, 540, 34, 34, fill=(30, 30, 30), ow=4)
        a = math.radians(t * 40 * (k + 1)); p.line([(xx, 540), (xx + 24 * math.cos(a), 540 + 24 * math.sin(a))], 4, WHITE)
    p.rect(1050, 620, 1380, 690, fill=(30, 50, 34), ow=4)
    blink = 1 if key_on(SOS1, t) or (int(t * 2) % 2) else 0
    p.ellipse(1370, 500, 18, 18, fill=(255, 60, 60) if blink else (110, 30, 30), ow=4)
    if blink:
        g = Image.new('L', img.size, 0); ImageDraw.Draw(g).ellipse([1300 * S, 430 * S, 1440 * S, 570 * S], fill=120)
        img.paste(Image.new('RGB', img.size, (255, 80, 60)), (0, 0), g.filter(ImageFilter.GaussianBlur(30 * S)))
    down = key_on(SOS1, t)
    tap = 8 if down else 0
    spec = dict(coat=(70, 96, 120), hat='headphones', expr='scared' if t < 18 else 'terrified', legs=False,
                la=-20, lb=-80, ra=20, rb=-55 + tap, look=(.5, .4), sweat=1 if t < 15 else 2, shake=.3 if t > 18 else 0, collar='v', buttons=2)
    hx, hy = arm_end(720, 470, 1.6, 1, spec['ra'], spec['rb'])
    morse_key(p, hx, hy + 12, down, 1.3)
    person(p, 720, 470, 1.6, spec, t)
    return img, (0.5 - .04 * ease((t - 7) / 17), 0.5, 1.0 + .18 * ease((t - 7) / 17))

MAP_SUM = [(250, 300), (360, 330), (520, 430), (690, 520), (860, 640), (1040, 760), (1210, 880), (1330, 1000), (1380, 1100), (900, 1100), (760, 980), (600, 840), (440, 680), (300, 520), (200, 380)]
MAP_MAL = [(760, -20), (1440, -20), (1450, 120), (1360, 200), (1320, 320), (1390, 470), (1440, 600), (1460, 720), (1400, 790), (1330, 770),
           (1250, 690), (1150, 590), (1060, 470), (980, 360), (920, 250), (860, 160), (800, 90)]
def sc_map(t, b):
    img = new_canvas((196, 226, 232)); p = Pen(img, b)
    for k in range(40):  # sea hatching
        xx, yy = (k * 211) % 1900, (k * 137) % 1060
        p.line([(xx, yy), (xx + 30, yy)], 2.5, (160, 200, 210))
    p.poly(MAP_SUM, fill=(244, 232, 160), ow=7, amp=3)
    p.poly(MAP_MAL, fill=(244, 232, 160), ow=7, amp=3)
    p.text(560, 760, 'سومطرة', 'kufi', 56, (150, 110, 60))
    p.text(1190, 520, 'الملايو', 'kufi', 56, (150, 110, 60))
    p.text(870, 455, 'مضيق مَلَقا', 'kufi', 46, (60, 110, 140))
    p.dot(1395, 800, 10, RED); p.text(1520, 760, 'سنغافورة', 'kufi', 34)
    # stations
    for (sx, sy, lab) in ((560, 520, 'محطة هولندية'), (1130, 360, 'محطة بريطانية')):
        pulse = (t * 1.3) % 1
        p.ellipse(sx, sy - 40, 40 + 140 * pulse, 40 + 140 * pulse, ow=4 * (1 - pulse) + .5, oc=(60, 110, 140))
        person(p, sx, sy - 70, .42, dict(coat=(70, 96, 120), hat='headphones', expr='worried', legs=True, la=15, ra=15, buttons=0), t)
        p.rect(sx - 110, sy + 50, sx + 110, sy + 100, fill=WHITE, ow=4)
        p.text(sx, sy + 75, lab, 'kufi', 28)
    # the ship with distress rings
    sx, sy = 930, 690
    for k in range(3):
        ph = (t * .8 + k / 3) % 1
        p.ellipse(sx, sy - 40, 60 + 260 * ph, 40 + 170 * ph, ow=6 * (1 - ph) + .5, oc=RED)
    ship(p, sx, sy, .38, col=(60, 60, 70))
    p.rect(sx - 140, sy + 40, sx + 140, sy + 92, fill=WHITE, ow=4)
    p.text(sx, sy + 66, 'أورانغ ميدان', 'kufi', 30, RED)
    # date card
    if t > 36.2:
        a = int(t * 4) % 2
        p.rect(300, 290, 640, 420, fill=WHITE, ow=6)
        p.text(470, 355, '١٩٤٧ ؟' if a else '١٩٤٨ ؟', 'kufi', 70, RED)
    z = ease((t - 30) / 8)
    return img, (0.5 - .02 * z, 0.5 + .08 * z, 1.0 + .35 * z)

def sc_board(t, b):
    img = radial_bg((150, 112, 76), (232, 204, 156), cx=.45, cy=.4, rad=.9); p = Pen(img, b)
    p.rect(0, 900, 1920, 1080, fill=(168, 120, 78), ow=6)
    # easel
    p.limb([(560, 260), (480, 1000)], 20, (150, 104, 60)); p.limb([(1280, 260), (1360, 1000)], 20, (150, 104, 60))
    p.rect(470, 150, 1370, 210, fill=(196, 146, 92), ow=6)
    p.rect(500, 205, 1340, 860, fill=(252, 250, 244), ow=6)
    p.text(920, 280, 'نص الرسالة', 'kufi', 60, RED)
    p.line([(780, 330), (1060, 335)], 5, RED)
    lines = [(44.0, '١- جميع الضباط، بمن فيهم القبطان، موتى'), (47.4, '٢- ممددون في غرفة الخرائط وعلى المنصة'), (50.8, '٣- ربما مات الطاقم كله')]
    for k, (ta, txt) in enumerate(lines):
        if t >= ta:
            y = 430 + k * 140
            p.text(1310, y, txt, 'amirib', 42, INK, anchor='rm')
            # icons
            ix = 565
            if k == 0: hat(p, ix, y + 40, .5, 'captain')
            elif k == 1: p.rect(ix - 34, y - 26, ix + 34, y + 26, fill=(236, 220, 150), ow=4); p.line([(ix - 25, y), (ix + 25, y - 10)], 3, RED)
            else: p.ellipse(ix, y, 34, 34, fill=WHITE, ow=4); p.arc(ix - 12, y - 6, 6, 4, 10, 170, 3); p.arc(ix + 12, y - 6, 6, 4, 10, 170, 3); p.dot(ix, y + 14, 6, INK)
    if t > 52.6:  # red slash: "no fire / no attack / no sinking"
        for k, w in enumerate(['حريق', 'هجوم', 'غرق']):
            if t > 53.4 + k * .9:
                xx = 1610; yy = 360 + k * 150
                p.text(xx, yy, w, 'kufi', 72, (60, 56, 56))
                p.line([(xx - 120, yy + 26), (xx + 120, yy - 26)], 12, RED)
    # investigator pointing
    point = ease((t - 43.5) / .6)
    person(p, 1640 if t < 52.4 else 300, 600, 1.35, dict(coat=(176, 150, 102), hat='fedora', expr='determined', mustache=True,
           glasses=True, la=10, ra=(-120 * point if t < 52.4 else 15), rb=0, look=(-1, 0) if t < 52.4 else (1, 0), collar='v', btn=(60, 50, 40), buttons=3), t)
    return img, (0.5, 0.5, 1.0 + .06 * ease((t - 42) / 18))

def sc_terror(t, b):
    k = ease((t - 60) / 7)
    grey = clamp01((t - 72.2) / .8)
    c_out = tuple(int(a * (1 - grey) + 30 * grey) for a in (150, 30, 30))
    c_in = tuple(int(a * (1 - grey) + 70 * grey) for a in (250, 200, 110))
    img = radial_bg(c_out, c_in, cx=.68, cy=.45, rad=.9); p = Pen(img, b + int(t * 6) if t < 67 else b)
    p.rect(0, 840, 1920, 1080, fill=(110, 72, 44), ow=6)
    down = key_on(GARB, t) or key_on(IDIE, t)
    collapse = ease((t - 72.0) / .5)
    spec = dict(coat=(70, 96, 120), hat='headphones', expr='terrified' if collapse < .5 else 'dead', legs=False,
                la=20, lb=-60, ra=-30, rb=-70 + (12 if down else 0), sweat=3, shake=(1.0 if t < 72 else 0), look=(0, -.2),
                head_dy=collapse * 120, head_dx=collapse * 40, buttons=2)
    spec['ra'], spec['rb'] = 22, -50 + (10 if down else 0)
    hx, hy = arm_end(560, 560 + collapse * 60, 2.2, 1, spec['ra'], spec['rb'])
    morse_key(p, hx, hy + 14, down, 1.6)
    person(p, 560, 560 + collapse * 60, 2.2, spec, t)
    # decoded letters
    shown = ''
    k_ = 0
    for ch in 'I DIE':
        if ch == ' ': shown += '  '; continue
        n = len(CODE[ch]); e = IDIE[k_ + n - 1][1]; k_ += n
        if t >= e: shown += ch + ' '
    if shown.strip():
        p.text(1100, 300, shown.strip(), 'kufi', 120, RED if grey < .5 else (90, 90, 90), anchor='mm')
    if t >= IDIE_END:
        p.text(1100, 470, 'أنا… أموت', 'amirib', 96, WHITE if grey < .5 else (150, 150, 150), stroke=3, sc=INK)
    sh = (1 - collapse) * (.012 if 61 < t < 72 else 0)
    zz = 1.0 + .25 * k
    return img, (0.42 + sh * math.sin(t * 53), 0.48 + sh * math.cos(t * 47), zz)

def sc_bridge(t, b):
    img = spotlight_bg((126, 104, 170), (206, 186, 226), cx=.5); p = Pen(img, b)
    p.rect(0, 900, 1920, 1080, fill=(96, 78, 136), ow=0)
    # thought bubble
    p.ellipse(960, 230, 300, 150, fill=WHITE, ow=6)
    for (bx, by, r) in ((1180, 400, 30), (1220, 450, 18), (1250, 490, 10)):
        p.ellipse(bx, by, r, r, fill=WHITE, ow=5)
    i = int((t - 82.4) / 1.6) if t > 82.4 else -1
    if i == 0 or i >= 3:  # pirate flag
        p.rect(820, 150, 1000, 280, fill=INK, ow=4); p.ellipse(910, 200, 34, 30, fill=WHITE, ow=0)
        p.line([(860, 250), (960, 270)], 8, WHITE); p.line([(860, 270), (960, 250)], 8, WHITE)
    if i == 1 or i >= 3:  # sea mine
        cx = 1060 if i >= 3 else 960
        for k in range(8):
            a = math.radians(k * 45); p.line([(cx + 55 * math.cos(a), 230 + 55 * math.sin(a)), (cx + 85 * math.cos(a), 230 + 85 * math.sin(a))], 8)
        p.ellipse(cx, 230, 60, 60, fill=(60, 60, 66), ow=5)
    if i == 2 or i >= 3:  # plague
        cx = 1150 if i >= 3 else 960
        p.ellipse(cx, 230, 60, 52, fill=(150, 200, 90), ow=5); p.text(cx, 230, '؟', 'kufi', 70, INK)
    if i < 0:
        p.text(960, 230, '…', 'kufi', 120)
    # captain with binoculars + sailors
    raise_ = ease((t - 87.6) / .5)
    spec = dict(coat=NAVY, hat='captain', expr='determined', beard=True, la=-140 * raise_ - 20 * (1 - raise_), lb=-40 * raise_,
                ra=-140 * raise_ - 20 * (1 - raise_), rb=-40 * raise_, look=(0, -.6 * raise_), collar='v', buttons=4)
    hands, (hx, hy) = person(p, 960, 560, 1.25, spec, t)
    if raise_ > .5:
        for sx in (-1, 1): p.ellipse(hx + sx * 22, hy - 4, 22, 24, fill=INK, ow=3)
    person(p, 560, 620, 1.05, dict(coat=(70, 110, 170), hat='sailor', expr='worried', collar='sailor', la=15, ra=40, rb=-60, sweat=1, buttons=0), t)
    person(p, 1380, 620, 1.05, dict(coat=(70, 110, 170), hat='beanie', expr='scared', collar='sailor', la=40, lb=-60, ra=15, look=(-.6, 0), buttons=0), t)
    if t > 88.0:  # "found her" stamp
        a = ease((t - 88.0) / .25)
        p.rect(1500, 120, 1840, 230, fill=(250, 240, 230), ow=6, oc=RED)
        p.text(1670, 175, 'وجدوها!', 'kufi', 56, RED)
    return img, (0.5, 0.5, 1.0 + .08 * ease((t - 76) / 16))

def sc_board_ship(t, b):
    T = t - 92
    dark = new_canvas((12, 16, 30)); lit = radial_bg((60, 64, 84), (120, 120, 140), cx=.5, cy=.5, rad=1.0)
    for img in (lit,):
        p = Pen(img, b)
        p.rect(0, 760, 1920, 1080, fill=(100, 92, 86), ow=6)
        for k in range(12): p.line([(k * 170, 760), (k * 170 - 60, 1080)], 3, (80, 72, 66))
        p.rect(1380, 300, 1920, 760, fill=(86, 86, 96), ow=6)   # bridge house wall
        p.rect(1460, 380, 1570, 480, fill=(30, 40, 60), ow=5); p.rect(1700, 380, 1810, 480, fill=(30, 40, 60), ow=5)
        # dead captain lying
        p.limb([(860, 930), (1120, 935)], 70, NAVY); p.ellipse(800, 910, 56, 58, fill=WHITE, ow=5.5)
        face(p, 800, 910, 1.0, 'dead'); hat(p, 740, 930, .8, 'captain')
        p.limb([(1070, 910), (1160, 850)], 22, NAVY); p.ellipse(1166, 842, 16, 15, fill=INK, ow=2)
        # dog
        dog(p, 1160, 760, 0.95)
        # radio operator slumped at a window desk
        p.rect(1480, 610, 1820, 760, fill=(118, 78, 46), ow=5)
        person(p, 1640, 520, .9, dict(coat=(70, 96, 120), hat='headphones', expr='dead', legs=False, la=10, ra=-60, rb=-40, head_dy=40, head_dx=30, buttons=0), t)
    # darkness version
    darkimg = Image.blend(lit, dark, .86)
    # flashlight cones (targets move over time)
    m = Image.new('L', lit.size, 0); dm = ImageDraw.Draw(m)
    tg1 = (900, 910) if T < 6 else (1230, 720) if T < 12 else (1640, 480)
    tg2 = (820, 890) if T < 6.5 else (1280, 760) if T < 12.5 else (1600, 560)
    O1 = arm_end(330, 560, 1.1, 1, 75, -20); O2 = arm_end(560, 580, 1.0, 1, 75, -25)
    for (ox, oy), (tx, ty), ph in ((O1, tg1, 0), (O2, tg2, 1.7)):
        tx += 40 * math.sin(T * 1.3 + ph); ty += 20 * math.cos(T * 1.1 + ph)
        ang = math.atan2(ty - oy, tx - ox); L = math.hypot(tx - ox, ty - oy) + 160; wd = .28
        pts = [(ox, oy), (ox + L * math.cos(ang - wd), oy + L * math.sin(ang - wd)), (ox + L * math.cos(ang + wd), oy + L * math.sin(ang + wd))]
        dm.polygon([(x * S, y * S) for x, y in pts], fill=200)
        dm.ellipse([(tx - 190) * S, (ty - 150) * S, (tx + 190) * S, (ty + 150) * S], fill=235)
    m = m.filter(ImageFilter.GaussianBlur(28 * S))
    img = Image.composite(lit, darkimg, m)
    warm = Image.new('RGB', img.size, (255, 230, 150))
    img = Image.composite(Image.blend(img, warm, .12), img, m)
    p = Pen(img, b)
    # sailors (foreground, lit by spill)
    for (hx, hy) in (O1, O2):
        p.poly([(hx - 10, hy - 16), (hx + 46, hy - 22), (hx + 50, hy + 10), (hx - 6, hy + 14)], fill=(200, 200, 205), ow=4)
    person(p, 330, 560, 1.1, dict(coat=(70, 110, 170), hat='sailor', expr='scared', collar='sailor', ra=75, rb=-20, la=20, sweat=2, look=(.8, .5), buttons=0), t)
    person(p, 560, 580, 1.0, dict(coat=(70, 110, 170), hat='beanie', expr='terrified', collar='sailor', ra=75, rb=-25, la=25, sweat=1, look=(.8, .4), shake=.4, buttons=0), t)
    # fog band
    fog = Image.new('L', img.size, 0); df = ImageDraw.Draw(fog)
    for k in range(9):
        xx = ((k * 260 + T * 40) % 2400) - 240
        df.ellipse([xx * S, (900 + (k % 3) * 40) * S, (xx + 420) * S, (1060 + (k % 3) * 40) * S], fill=70)
    img.paste(Image.new('RGB', img.size, (170, 180, 200)), (0, 0), fog.filter(ImageFilter.GaussianBlur(30 * S)))
    cam = (0.42, 0.6, 1.15) if T < 6 else ((0.55, 0.6, 1.3) if T < 12 else (0.68, 0.5, 1.3))
    return img, cam

def polaroid(p, x, y, ang_seed, label, year, kind):
    p.rect(x - 170, y - 200, x + 170, y + 200, fill=(246, 244, 238), ow=6)
    p.rect(x - 140, y - 170, x + 140, y + 90, fill=(120, 120, 120), ow=5)
    if kind == 0:  # newspaper
        p.rect(x - 100, y - 140, x + 100, y + 60, fill=(220, 220, 214), ow=4)
        for k in range(6): p.line([(x - 80, y - 110 + k * 28), (x + 80, y - 110 + k * 28)], 4, (110, 110, 110))
        p.rect(x - 80, y - 135, x + 80, y - 115, fill=INK, ow=0)
    elif kind == 1:  # bulletin booklet
        p.rect(x - 80, y - 150, x + 80, y + 70, fill=(200, 200, 190), ow=4)
        p.ellipse(x, y - 60, 40, 40, fill=(90, 90, 90), ow=4); p.line([(x - 50, y + 20), (x + 50, y + 20)], 4, (110, 110, 110))
    else:  # book
        p.poly([(x - 110, y - 120), (x, y - 100), (x + 110, y - 120), (x + 110, y + 60), (x, y + 70), (x - 110, y + 60)], fill=(214, 214, 206), ow=4)
        p.line([(x, y - 100), (x, y + 70)], 4)
        for k in range(4): p.line([(x - 90, y - 80 + k * 30), (x - 20, y - 76 + k * 30)], 3, (110, 110, 110)); p.line([(x + 20, y - 80 + k * 30), (x + 90, y - 76 + k * 30)], 3, (110, 110, 110))
    p.text(x, y + 128, label, 'amirib', 34)
    p.text(x, y + 170, year, 'kufi', 26, (110, 110, 110))

def sc_polaroids(t, b):
    img = new_canvas((92, 88, 84)); p = Pen(img, b)
    for k in range(9):
        p.line([(0, k * 125), (1920, k * 125 + 6)], 5, (70, 66, 62))
        for j in range(5): p.line([(j * 410 + k * 60 % 300, k * 125 + 40), (j * 410 + k * 60 % 300 + 160, k * 125 + 44)], 2, (110, 104, 98))
    items = [(113.4, 470, 'صحيفة هولندية', '١٩٤٨', 0), (115.4, 960, 'نشرة خفر السواحل', '١٩٥٢', 1), (117.4, 1450, 'كتاب أوتو ميلكه', '١٩٥٤', 2)]
    for ta, x, lab, yr, kind in items:
        if t >= ta:
            drop = 1 - ease((t - ta) / .3)
            polaroid(p, x, 470 - 300 * drop, 0, lab, yr, kind)
    if t > 119:  # red string
        for (a, c) in ((470, 960), (960, 1450)):
            k = ease((t - 119) / .8)
            p.line([(a, 290), (a + (c - a) * k, 290 + 30 * math.sin(k * math.pi))], 5, RED)
        for x in (470, 960, 1450): p.dot(x, 290, 12, RED)
    if t > 120.5:  # stamps
        for k, w in enumerate(['لا سجل', 'لا مالك', 'لا طاقم', 'لا تحقيق']):
            if t > 120.5 + k * .7:
                p.rect(220 + k * 400, 730, 520 + k * 400, 820, fill=(240, 230, 220), ow=7, oc=RED)
                p.text(370 + k * 400, 775, w, 'kufi', 46, RED)
    if t > 124:
        a = ease((t - 124) / .4)
        p.text(960, 470, '؟', 'kufi', int(380 * (1.4 - .4 * a)), RED, stroke=6, sc=INK)
    return img, (0.5, 0.5, 1.0 + .07 * ease((t - 112) / 18))

def sc_title(t, b):
    T = t - 130
    img = radial_bg((30, 10, 34), (150, 34, 54), cx=.6, cy=.75, rad=1.0)
    p = Pen(img, b)
    for k in range(80):
        p.dot((k * 241) % 1920, (k * 113) % 620, 2 + (k % 3), (255, 200, 220))
    p.rect(0, 860, 1920, 1080, fill=(110, 24, 36), ow=0)
    # ghost ship with chromatic outline and eyes
    rise = ease(T / 3.0)
    gx, gy = 1330, 600 - 40 * math.sin(T * .9) - 60 * rise
    for col, dx in (((40, 220, 240), -9), ((240, 40, 60), 9)):
        ship(p, gx + dx, gy, 1.5, col=(10, 6, 14), oc=col)
    ship(p, gx, gy, 1.5, eyes=T > 2.5, col=(8, 4, 12), oc=(8, 4, 12))
    # small terrified operator bottom-left
    person(p, 300, 820, 1.0, dict(coat=(70, 96, 120), hat='headphones', expr='terrified', sweat=2, la=-30, lb=-60, ra=40, rb=-90, look=(1, -.3), shake=.6, buttons=2), t)
    # glowing title
    a = ease((T - 3.0) / .6)
    if a > 0:
        g = Image.new('RGB', img.size, (0, 0, 0)); pg = Pen(g, b)
        pg.text(560, 240, 'سفينة الأشباح', 'kufi', 108, (255, 60, 70))
        pg.text(560, 390, 'في المضيق', 'kufi', 108, (255, 60, 70))
        img = Image.fromarray(np.clip(np.asarray(img, np.int16) + (np.asarray(g.filter(ImageFilter.GaussianBlur(18 * S)), np.int16) * a).astype(np.int16), 0, 255).astype(np.uint8))
        p = Pen(img, b)
        col = tuple(int(255 * a + c * (1 - a)) for c in (40, 10, 30))
        p.text(560, 240, 'سفينة الأشباح', 'kufi', 108, (255, 236, 236) if a > .9 else col, stroke=2, sc=(255, 60, 70))
        p.text(560, 390, 'في المضيق', 'kufi', 108, (255, 236, 236) if a > .9 else col, stroke=2, sc=(255, 60, 70))
    if T > 5.5:
        p.text(700, 540, 'الأسطورة', 'kufi', 52, RED); p.text(560, 540, '/', 'kufi', 52, (200, 200, 200)); p.text(440, 540, 'السجلّ', 'kufi', 52, AMBER)
    return img, (0.5, 0.5, 1.0 + .05 * ease(T / 30))

SCENES = [(0, 7, sc_intro), (7, 24, sc_radio), (24, 42, sc_map), (42, 60, sc_board), (60, 76, sc_terror),
          (76, 92, sc_bridge), (92, 112, sc_board_ship), (112, 130, sc_polaroids), (130, 160.1, sc_title)]

# ======================================================================== compositing
CAPIMG = {}
def cap_img(txt):
    if txt not in CAPIMG:
        f = font('amirib', 56)
        tmp = ImageDraw.Draw(Image.new('L', (4, 4)))
        bb = tmp.textbbox((0, 0), txt, font=f, direction='rtl', language='ar')
        w, h = bb[2] - bb[0] + 60, bb[3] - bb[1] + 40
        im = Image.new('RGBA', (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, w - 1, h - 1], 18, fill=(10, 8, 12, 170))
        d.text((30 - bb[0], 20 - bb[1]), txt, font=f, fill=(255, 250, 240, 255), direction='rtl', language='ar')
        CAPIMG[txt] = im
    return CAPIMG[txt]

def camera(img, cam):
    cx, cy, z = cam
    cw, ch = W * S / z, H * S / z
    x0 = min(max(cx * W * S - cw / 2, 0), W * S - cw); y0 = min(max(cy * H * S - ch / 2, 0), H * S - ch)
    return img.resize((W, H), Image.LANCZOS, box=(x0, y0, x0 + cw, y0 + ch))

def scene_at(t, b):
    for a, e, fn in SCENES:
        if a <= t < e:
            img, cam = fn(t, b); return camera(img, cam)
    img, cam = SCENES[-1][2](t, b); return camera(img, cam)

def render(fi):
    t = fi / RFPS
    b = fi // 2 if t < 60 or t > 72 else fi    # line boil every 2 drawn frames (faster when panicking)
    frame = np.asarray(scene_at(t, b), np.float32)
    # whip transition: incoming slides from the right with motion blur
    for c in CUTS:
        if c <= t < c + .25:
            k = 1 - ease((t - c) / .25); off = int(k * 700)
            acc = np.zeros_like(frame)
            for j in range(6): acc += np.roll(frame, off + j * 40, axis=1)
            frame = acc / 6
        if c - .08 <= t < c + .04:
            frame = frame * .4 + 255 * .6
    # chromatic glitch on panic + title reveal
    gl = (0.6 if 61 < t < 71 and int(t * 12) % 5 == 0 else 0) + (0.8 if 132.8 < t < 133.4 else 0)
    if gl:
        sh = int(14 * gl)
        frame[:, :, 0] = np.roll(frame[:, :, 0], sh, 1); frame[:, :, 2] = np.roll(frame[:, :, 2], -sh, 1)
    # lightning flash in radio room
    for L in LIGHTNING:
        if 0 <= t - L < .25: frame = frame + 90 * math.exp(-(t - L) * 14)
    img = Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8)).convert('RGBA')
    for a, e, txt in CAPS:
        al = fade(t, a, e)
        if al > 0:
            c = cap_img(txt)
            if al < 1:
                c = c.copy(); c.putalpha(c.split()[3].point(lambda v: int(v * al)))
            img.alpha_composite(c, ((W - c.width) // 2, H - c.height - 48))
    arr = np.asarray(img.convert('RGB'), np.float32)
    yy, xx = np.ogrid[0:H, 0:W]
    if 'vig' not in CAPIMG:
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
        CAPIMG['vig'] = np.clip(1.08 - .35 * r ** 2, .55, 1)[:, :, None].astype(np.float32)
    arr *= CAPIMG['vig']
    if t > 157.5: arr *= clamp01((160 - t) / 2.5) if not (159.0 <= t < 159.3) else 1
    if 159.0 <= t < 159.3:
        arr *= 0; arr[H // 2 - 20:H // 2 + 20, W // 2 - 20:W // 2 + 20] = (255, 60, 60)
    return np.clip(arr, 0, 255).astype(np.uint8)

def chunk(args):
    ci, a, b = args
    path = os.path.join(OUT, f'cpart{ci}.mp4')
    pr = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(RFPS), '-i', '-',
                           '-vf', f'fps={OFPS}', '-c:v', 'libx264', '-preset', 'medium', '-crf', '19', '-pix_fmt', 'yuv420p', path], stdin=subprocess.PIPE)
    for i in range(a, b): pr.stdin.write(render(i).tobytes())
    pr.stdin.close(); pr.wait(); return path

# ======================================================================== audio
SR = 48000
def audio(path):
    n = int(DUR * SR); t = np.arange(n) / SR; rng = np.random.default_rng(3)
    out = np.zeros(n)
    def env(a, b, fi=.5, fo=.5): return np.clip((t - a) / fi, 0, 1) * np.clip((b - t) / fo, 0, 1)
    def lp(x, k):
        y = x.copy()
        for _ in range(3): y = np.convolve(y, np.ones(k) / k, 'same')
        return y
    noise = rng.normal(0, 1, n); rum = lp(noise, 300) * 6; hiss = noise - lp(noise, 6)
    drone = np.sin(2 * np.pi * 43 * t) + .6 * np.sin(2 * np.pi * 64.5 * t + np.sin(t * .4))
    out += .09 * drone * (env(6.5, 60.2, 1, .1) + env(76, 112, .3, .2) + .6 * env(112, 130, .2, .2))
    out += .03 * hiss * env(7, 24, .5, .1) * (.5 + .5 * np.sin(t * 9) ** 2)            # rain in the radio room
    out += .18 * rum * env(92, 112, .5, .3)                                               # deck rumble
    def beep(evs, f=680, amp=.22):
        for a, b in evs:
            i0, i1 = int(a * SR), int(b * SR); s = np.arange(i1 - i0) / SR
            out[i0:i1] += amp * np.sin(2 * np.pi * f * s) * np.minimum(1, np.minimum(s / .004, (b - a - s) / .004))
    beep(SOS0 + SOS0b); beep(SOS1, amp=.18); beep(GARB, 700, .14); beep(IDIE, 700, .22); beep(LAST, 680, .2)
    out += .03 * hiss * env(60.5, 67.2, .2, .1)
    # rising tension under the terror scene
    s = np.clip((t - 60) / 11, 0, 1)
    out += .06 * np.sin(2 * np.pi * (200 * t + 160 * s * (t - 60))) * env(60, 72.1, 1, .02)
    for L in LIGHTNING:
        i0 = int(L * SR); Ls = int(2 * SR); ss = np.arange(Ls) / SR
        out[i0:i0 + Ls] += .4 * hiss[:Ls] * np.exp(-ss * 12) + .8 * rum[:Ls] * np.exp(-ss * 1.6)
    for c in CUTS:  # whoosh on whip transitions
        i0 = int((c - .2) * SR); Ls = int(.5 * SR); ss = np.arange(Ls) / SR
        w = np.sin(np.pi * ss / .5) ** 2
        out[i0:i0 + Ls] += .25 * lp(hiss[:Ls], 3) * w
    # stings / hits
    for hit in (44.0, 47.4, 50.8, 53.4, 54.3, 55.2, 88.0, 113.4, 115.4, 117.4, 120.5, 121.2, 121.9, 122.6, 124.0):
        i0 = int(hit * SR); Ls = int(.9 * SR); ss = np.arange(Ls) / SR
        out[i0:i0 + Ls] += .5 * np.sin(2 * np.pi * (70 * ss - 25 * ss * ss)) * np.exp(-ss * 6) + .2 * hiss[:Ls] * np.exp(-ss * 50)
    # heartbeat while boarding
    for k in range(int((112 - 92.5) / .85)):
        for dd, a in ((0, .6), (.18, .4)):
            hb = 92.5 + k * .85 + dd; i0 = int(hb * SR); Ls = int(.25 * SR); ss = np.arange(Ls) / SR
            out[i0:i0 + Ls] += a * np.sin(2 * np.pi * 52 * ss) * np.exp(-ss * 22)
    # collapse thud + silence handled by envelopes
    i0 = int(72.1 * SR); Ls = int(1.5 * SR); ss = np.arange(Ls) / SR
    out[i0:i0 + Ls] += .9 * np.sin(2 * np.pi * 45 * ss) * np.exp(-ss * 5)
    # quirky pizzicato motif on map + board (light, "explainer" feel)
    notes = [(25.0, 392), (25.5, 440), (26.0, 523), (27.0, 494), (29.0, 392), (29.5, 349), (30.0, 392), (33.0, 440), (33.5, 523), (37.0, 587), (37.5, 523),
             (43.0, 330), (43.5, 392), (45.0, 349), (48.5, 330), (52.0, 294)]
    for nt, f in notes:
        s2 = t - nt; m = s2 > 0
        out += .07 * m * np.exp(-np.clip(s2, 0, None) * 9) * np.sin(2 * np.pi * f * s2)
    # title: horn + glitch + piano
    s2 = t - 133.0; m = (s2 > 0) & (s2 < 6)
    out += .17 * lp((np.sign(np.sin(2 * np.pi * 73 * s2)) * .5 + np.sin(2 * np.pi * 110 * s2)) * np.clip(s2 / .3, 0, 1) * np.clip((6 - s2) / 2.5, 0, 1) * m, 12)
    out += .25 * hiss * env(132.8, 133.4, .02, .05)
    for nt, f in [(140, 220), (141.2, 261.6), (142.4, 329.6), (144.4, 293.7), (146, 220), (147.2, 261.6), (148.4, 246.9), (151, 196), (154, 220)]:
        s2 = t - nt; m = s2 > 0
        out += .09 * m * np.exp(-np.clip(s2, 0, None) * 1.6) * (np.sin(2 * np.pi * f * s2) + .4 * np.sin(4 * np.pi * f * s2))
    rev = out.copy()
    for d, g in ((.031, .3), (.047, .26), (.071, .22), (.113, .18), (.173, .12)):
        k = int(d * SR); rev[k:] += g * out[:-k]
    out = np.tanh(rev * 1.15) * .9 * np.clip((DUR - .05 - t) / .3, 0, 1)
    st = (np.stack([out, out], 1) * 32767).astype(np.int16)
    with wave.open(path, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(st.tobytes())

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    if len(sys.argv) > 3:
        for ts in sys.argv[3:]:
            Image.fromarray(render(int(round(float(ts) * RFPS)))).save(os.path.join(OUT, f'c_{ts}.png'))
        sys.exit()
    audio(os.path.join(OUT, 'caudio.wav'))
    N = int(DUR * RFPS); nproc = os.cpu_count() or 4
    bounds = np.linspace(0, N, nproc * 2 + 1).astype(int)
    with Pool(nproc) as pool:
        parts = pool.map(chunk, [(i, bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)])
    lst = os.path.join(OUT, 'cparts.txt'); open(lst, 'w').write(''.join(f"file '{q}'\n" for q in parts))
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-i', os.path.join(OUT, 'caudio.wav'),
                    '-c:v', 'libx264', '-preset', 'slow', '-b:v', '6M', '-maxrate', '8M', '-bufsize', '16M', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', os.path.join(OUT, 'ourang-medan-cartoon.mp4')], check=True)
    for q in parts: os.remove(q)
    print('done')
