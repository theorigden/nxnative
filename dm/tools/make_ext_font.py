#!/usr/bin/env python3
# Generate a stand-in for the "Nintendo extension" shared font (nintendo_ext.ttf): controller-button icons at the original private-use code points (A/B/X/Y, L/R/ZL/ZR/SL/SR, +/−, D-pad, stick direction arrows).
# The host has no original system fonts; button icons in game text (e.g. Mario's GameMsg/Key.msbt: U+E0E0 = A button) render as "?" when the glyph is missing. Letters come from macOS's Arial Rounded Bold, knocked out of a solid plate.
# Icon styles (DM_BUTTON_ICONS; docs/reference/services.md, "Button icons of the player's controller"): besides the Switch's own, the same font with the buttons of an Xbox or a PlayStation controller, one
# file per style and face mapping (VARIANTS: nintendo_ext_<variant>.ttf). The icon a Switch button gets is the button the player presses for it, which follows DM_PAD_FACE (pad_apple.h): by position
# (the default) the Switch's A is the right button (Xbox B, PlayStation circle), by label the bottom one (Xbox A, cross). Games draw these fonts as alpha (the font engine's glyph cache is an alpha
# texture, the colour is the text's), so the icons are monochrome: the shapes and letters of those controllers' buttons, drawn here as simple geometric outlines, not their artwork.
# restyle() puts the same icons into a game's own button-icon font (dm/tools/game_icon_font.py; the profile's icon_font key), glyph by glyph, keeping the rest of that font as it is.
# Usage: make_ext_font.py out.ttf [letter-font.ttf]   (writes out.ttf and its variants beside it); needs fontTools (pip install fonttools)
import math, os, sys
from fontTools.ttLib import TTFont
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.reverseContourPen import ReverseContourPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen

EM, ASC, DESC = 1000, 880, -120
CY, R = 350, 450          # icon centre height and circle radius: -100 to 800, sitting on the baseline
LETTERS = '/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf'

# The pad button at each place of the right-hand face buttons, and the place the player presses for each Switch face button
PAD = {'xbox': {'bottom': 'A', 'right': 'B', 'left': 'X', 'top': 'Y'},
       'playstation': {'bottom': 'cross', 'right': 'circle', 'left': 'square', 'top': 'triangle'}}
PLACE = {'position': {'A': 'right', 'B': 'bottom', 'X': 'top', 'Y': 'left'},   # DM_PAD_FACE=position (the default): the Switch's layout
         'label': {'A': 'bottom', 'B': 'right', 'X': 'left', 'Y': 'top'}}       # DM_PAD_FACE=label: the pad's letters (an Xbox pad's A, at the bottom, is the Switch's A)
# Variant name (the file suffix the host asks for: button_icons.h bi_variant) → (style, face mapping); '' is the Switch's own
VARIANTS = {'': ('switch', None), 'xbox': ('xbox', 'position'), 'xbox_label': ('xbox', 'label'),
            'playstation': ('playstation', 'position'), 'playstation_label': ('playstation', 'label')}
def variant_path(path, variant):   # nintendo_ext.ttf → nintendo_ext_xbox.ttf
    if not variant: return path
    stem, ext = os.path.splitext(path); return f'{stem}_{variant}{ext}'
def pad_button(style, face, button):   # the pad's button the player presses for a Switch face button (A, B, X, Y), in a style's names
    return PAD[style][PLACE[face][button]]

def area(c): return sum(c[i][0] * c[i - 1][1] - c[i - 1][0] * c[i][1] for i in range(len(c))) / 2
def contour(pen, pts, hole=False):
    # solid clockwise, hole counter-clockwise (TrueType convention, nonzero winding)
    if (area(pts) > 0) != hole: pts = pts[::-1]
    k = next(i for i, p in enumerate(pts) if p[2]); pts = pts[k:] + pts[:k]
    pen.moveTo(pts[0][:2]); offs = []
    for x, y, on in pts[1:]:
        if not on: offs.append((x, y)); continue
        if offs: pen.qCurveTo(*offs, (x, y)); offs = []
        else: pen.lineTo((x, y))
    if offs: pen.qCurveTo(*offs, pts[0][:2])
    pen.closePath()
def circle(cx, cy, r, n=8):
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n; b = a + math.pi / n; rr = r / math.cos(math.pi / n)
        pts += [(round(cx + r * math.cos(a)), round(cy + r * math.sin(a)), 1), (round(cx + rr * math.cos(b)), round(cy + rr * math.sin(b)), 0)]
    return pts
def rrect(x0, y0, x1, y1, rad, rad_top=None):   # rad_top: another radius for the top corners (a trigger's rounded top)
    rad = min(rad, (x1 - x0) / 2, (y1 - y0) / 2); rt = rad if rad_top is None else min(rad_top, (x1 - x0) / 2, (y1 - y0) / 2)
    return [(x0 + rt, y1, 1), (x1 - rt, y1, 1), (x1, y1, 0), (x1, y1 - rt, 1), (x1, y0 + rad, 1), (x1, y0, 0), (x1 - rad, y0, 1),
            (x0 + rad, y0, 1), (x0, y0, 0), (x0, y0 + rad, 1), (x0, y1 - rt, 1), (x0, y1, 0)]
def rect(x0, y0, x1, y1): return [(x0, y1, 1), (x1, y1, 1), (x1, y0, 1), (x0, y0, 1)]
def poly(pts): return [(round(x), round(y), 1) for x, y in pts]
def rot(pts, cx, cy, deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    return [(round(cx + (x - cx) * c - (y - cy) * s), round(cy + (x - cx) * s + (y - cy) * c), on) for x, y, on in pts]

class Letters:
    def __init__(self, path):
        self.f = TTFont(path); self.gs = self.f.getGlyphSet(); self.cmap = self.f.getBestCmap()
    def knock(self, pen, text, cx, cy, h, max_w=None):
        # knock text out of the plate, centred at (cx, cy) with height h (narrower to fit max_w)
        names = [self.cmap[ord(ch)] for ch in text]; x = 0; parts = []
        for nm in names: parts.append((nm, x)); x += self.gs[nm].width
        bp = BoundsPen(self.gs)
        for nm, dx in parts: self.gs[nm].draw(TransformPen(bp, (1, 0, 0, 1, dx, 0)))
        x0, y0, x1, y1 = bp.bounds; s = h / (y1 - y0)
        if max_w and (x1 - x0) * s > max_w: s = max_w / (x1 - x0)
        ox, oy = cx - (x0 + x1) / 2 * s, cy - (y0 + y1) / 2 * s
        # Knocked out = opposite direction to the plate. Fonts differ in outer-contour direction (TrueType clockwise, converted fonts often counter-clockwise); flip based on the largest contour's direction
        rec = RecordingPen()
        for nm, dx in parts: self.gs[nm].draw(TransformPen(rec, (s, 0, 0, s, ox + dx * s, oy)))
        rings, cur = [], []
        for op, args in rec.value:
            if op == 'moveTo': cur = [args[0]]; rings.append(cur)
            elif op in ('lineTo', 'qCurveTo', 'curveTo'): cur.extend(a for a in args if a is not None)
        big = max(rings, key=lambda c: abs(area(c)))
        rec.replay(ReverseContourPen(pen) if area(big) < 0 else pen)

def cross(cx, cy, half, arm):   # D-pad outline (one closed ring)
    a, h = arm / 2, half
    return [(cx - a, cy + h, 1), (cx + a, cy + h, 1), (cx + a, cy + a, 1), (cx + h, cy + a, 1), (cx + h, cy - a, 1), (cx + a, cy - a, 1),
            (cx + a, cy - h, 1), (cx - a, cy - h, 1), (cx - a, cy - a, 1), (cx - h, cy - a, 1), (cx - h, cy + a, 1), (cx - a, cy + a, 1)]

class Icons:
    """The button icons of a style: draw(button) → (draw(pen, cx), advance) for the Switch buttons A B X Y L R ZL ZR SL SR Plus Minus StickL StickR, in the font's units (EM 1000, centred on CY)"""
    def __init__(self, letters, style='switch', face='position'):
        self.L = letters if isinstance(letters, Letters) else Letters(letters); self.style = style; self.face = face or 'position'
    def round_btn(self, t):
        def d(pen, cx): contour(pen, circle(cx, CY, R)); self.L.knock(pen, t, cx, CY, 470)
        return d
    def plate(self, t, w, h=620, th=400, rad=220, rad_top=None):
        def d(pen, cx): contour(pen, rrect(cx - w / 2, CY - h / 2, cx + w / 2, CY + h / 2, rad, rad_top)); self.L.knock(pen, t, cx, CY - (40 if rad_top else 0), th, w - 160)
        return d
    def sign(self, minus):
        def d(pen, cx):
            contour(pen, circle(cx, CY, R)); t, l = 70, 250
            if minus: contour(pen, rect(cx - l, CY - t, cx + l, CY + t), hole=True)
            else: contour(pen, cross(cx, CY, l, 2 * t), hole=True)
        return d
    def stick(self, t):
        def d(pen, cx):
            contour(pen, circle(cx, CY, R)); contour(pen, circle(cx, CY, R - 70), hole=True); contour(pen, circle(cx, CY, 300))
            if t: self.L.knock(pen, t, cx, CY, 300 if len(t) < 2 else 240, 440)
        return d
    def menu(self):   # three bars in a disc: Xbox's Menu, PlayStation's Options
        def d(pen, cx):
            contour(pen, circle(cx, CY, R))
            for dy in (-150, 0, 150): contour(pen, rect(cx - 230, CY + dy - 45, cx + 230, CY + dy + 45), hole=True)
        return d
    def view(self):   # two overlapping windows in a disc: Xbox's View. The front one a frame, the back one only its edges that show (one L-shaped ring, so no knocked-out area overlaps another)
        def d(pen, cx):
            contour(pen, circle(cx, CY, R)); t, s, o = 55, 280, 110
            fx0, fy0 = cx - s / 2 + o / 2, CY - s / 2 - o / 2; fx1, fy1 = fx0 + s, fy0 + s
            contour(pen, rect(fx0, fy0, fx1, fy1), hole=True); contour(pen, rect(fx0 + t, fy0 + t, fx1 - t, fy1 - t))
            bx0, by1 = fx0 - o, fy1 + o
            contour(pen, poly([(bx0, by1), (fx1 - o, by1), (fx1 - o, by1 - t), (bx0 + t, by1 - t), (bx0 + t, fy0 + o), (bx0, fy0 + o)]), hole=True)
        return d
    def share(self):   # an arrow up out of a tray in a disc: PlayStation's Create (share)
        def d(pen, cx):
            contour(pen, circle(cx, CY, R)); t = 60
            contour(pen, poly([(cx - 230, CY + 40), (cx - 230, CY - 200), (cx + 230, CY - 200), (cx + 230, CY + 40), (cx + 230 - t, CY + 40), (cx + 230 - t, CY - 200 + t),
                               (cx - 230 + t, CY - 200 + t), (cx - 230 + t, CY + 40)]), hole=True)
            contour(pen, poly([(cx - t / 2, CY - 110), (cx - t / 2, CY + 120), (cx - 140, CY + 120), (cx, CY + 260), (cx + 140, CY + 120), (cx + t / 2, CY + 120), (cx + t / 2, CY - 110)]), hole=True)
        return d
    def ps_face(self, shape):   # a disc with the PlayStation button's symbol knocked out
        def d(pen, cx):
            contour(pen, circle(cx, CY, R))
            if shape == 'cross':
                contour(pen, rot(cross(cx, CY, 270, 80), cx, CY, 45), hole=True)
            elif shape == 'circle':
                contour(pen, circle(cx, CY, 250, 16), hole=True); contour(pen, circle(cx, CY, 170, 16))
            elif shape == 'square':
                contour(pen, rect(cx - 220, CY - 220, cx + 220, CY + 220), hole=True); contour(pen, rect(cx - 150, CY - 150, cx + 150, CY + 150))
            else:   # triangle, point up, centred on its centroid
                k = 270; o = [(cx + k * math.cos(math.radians(a)), CY + k * math.sin(math.radians(a))) for a in (90, 210, 330)]
                i = [(cx + (k - 150) * math.cos(math.radians(a)), CY + (k - 150) * math.sin(math.radians(a))) for a in (90, 210, 330)]
                contour(pen, poly(o), hole=True); contour(pen, poly(i))
        return d
    def draw(self, button):
        s = self.style
        if button in ('A', 'B', 'X', 'Y'):
            if s == 'switch': return self.round_btn(button), 1000
            b = pad_button(s, self.face, button)
            return (self.round_btn(b) if s == 'xbox' else self.ps_face(b)), 1000
        if button in ('L', 'R', 'ZL', 'ZR'):
            if s == 'switch': w = 900 if len(button) == 1 else 1200; return self.plate(button, w), w + 100
            side = button[-1]
            if s == 'xbox': t = side + ('B' if len(button) == 1 else 'T')
            else: t = side + ('1' if len(button) == 1 else '2')
            return (self.plate(t, 1200) if len(button) == 1 else self.plate(t, 1100, 760, rad=120, rad_top=380)), 1300 if len(button) == 1 else 1200
        if button in ('SL', 'SR'): return self.plate(button, 1200), 1300
        if button in ('Plus', 'Minus'):
            if s == 'switch': return self.sign(button == 'Minus'), 1000
            if button == 'Plus': return self.menu(), 1000
            return (self.view() if s == 'xbox' else self.share()), 1000
        if button in ('StickL', 'StickR'):
            side = button[-1]
            return self.stick(side if s == 'switch' else side + ('S' if s == 'xbox' else '3')), 1000
        raise KeyError(button)

def build(out, letter_font=LETTERS, style='switch', face=None):
    I = Icons(letter_font, style, face); glyphs = {}; adv = {}; cmap = {}
    def glyph(name, codes, width, draw):
        pen = TTGlyphPen(None); draw(pen, width / 2); glyphs[name] = pen.glyph(); adv[name] = width
        for c in codes: cmap[c] = name
    def btn(name, codes, button): d, w = I.draw(button); glyph(name, codes, w, d)
    def dpad(arm_dir):   # None = all solid; otherwise only one arm filled
        def d(pen, cx):
            contour(pen, cross(cx, CY, R, 320))
            if arm_dir is None: return
            contour(pen, cross(cx, CY, R - 55, 320 - 110), hole=True)
            arm = rect(cx - 105, CY + 105, cx + 105, CY + R - 55)
            contour(pen, rot(arm, cx, CY, {'up': 0, 'left': 90, 'down': 180, 'right': 270}[arm_dir]))
        return d
    def arrow(deg):
        def d(pen, cx):
            p = [(-380, 105, 1), (60, 105, 1), (60, 310, 1), (420, 0, 1), (60, -310, 1), (60, -105, 1), (-380, -105, 1)]
            contour(pen, rot([(cx + x, CY + y, on) for x, y, on in p], cx, CY, deg))
        return d

    pen = TTGlyphPen(None); glyphs['.notdef'] = pen.glyph(); adv['.notdef'] = 500
    for i, t in enumerate(['A', 'B', 'X', 'Y']): btn('btn' + t, [0xE0A0 + i, 0xE0E0 + i], t)
    for i, t in enumerate(['L', 'R', 'ZL', 'ZR', 'SL', 'SR']): btn('btn' + t, [0xE0A4 + i, 0xE0E4 + i], t)
    btn('btnPlus', [0xE0B5, 0xE0EF], 'Plus'); btn('btnMinus', [0xE0B6, 0xE0F0], 'Minus')
    glyph('dpad', [0xE0EA], 1000, dpad(None))
    for c, dr in [(0xE0AB, 'right'), (0xE0AC, 'down'), (0xE0AD, 'up'), (0xE0AE, 'left')]: glyph('dpad_' + dr, [c, c + 0x40], 1000, dpad(dr))
    for c, (nm, deg) in zip(range(0xE090, 0xE098), [('right', 0), ('left', 180), ('up', 90), ('down', 270), ('rightup', 45), ('rightdown', 315), ('leftdown', 225), ('leftup', 135)]):
        glyph('arrow_' + nm, [c], 1000, arrow(deg))
    glyph('stick', [0xE100], 1000, I.stick(None)); btn('stickL', [0xE101, 0xE0C1], 'StickL'); btn('stickR', [0xE102, 0xE0C2], 'StickR')
    # The other code points of the private-use block the real font covers get a plain ring: a game may take one of its glyphs without a null check (Super Mario 3D All-Stars' launcher
    # sets U+E06B as its font's alternate character at boot and read through the null glyph), and in text a ring is no worse than the "?" of a missing icon
    glyph('icon', [c for c in range(0xE000, 0xE200) if c not in cmap], 1000, lambda pen, cx: (contour(pen, circle(cx, CY, R)), contour(pen, circle(cx, CY, R - 70), hole=True)))

    order = ['.notdef'] + sorted(n for n in glyphs if n != '.notdef')
    fb = FontBuilder(EM, isTTF=True)
    fb.setupGlyphOrder(order); fb.setupCharacterMap(cmap); fb.setupGlyf(glyphs)
    glyf = fb.font['glyf']
    for n in order: glyf[n].recalcBounds(glyf)
    fb.setupHorizontalMetrics({n: (adv[n], getattr(glyf[n], 'xMin', 0)) for n in order})
    fb.setupHorizontalHeader(ascent=ASC, descent=DESC)
    fb.setupNameTable({'familyName': 'DM Nintendo Extension Stand-in', 'styleName': 'Regular', 'fullName': 'DM Nintendo Extension', 'psName': 'DM-Nintendo-Extension'})   # the full name is what the font engine reports (LoadFont): one of its own, as a game can load every shared font into one engine
    fb.setupOS2(sTypoAscender=ASC, sTypoDescender=DESC, sTypoLineGap=0, usWinAscent=ASC, usWinDescent=-DESC)
    fb.setupPost(); fb.save(out)
    print('%s: %d glyphs, %d code points%s' % (out, len(order), len(cmap), '' if style == 'switch' else f' ({style} icons, face buttons by {face})'))

def build_all(out, letter_font=LETTERS):   # the Switch's font at out and every other style beside it (variant_path)
    for v, (style, face) in VARIANTS.items(): build(variant_path(out, v), letter_font, style, face)

def restyle(font, buttons, style, face, letter_font=LETTERS):
    """A game's own button-icon font (a TTFont, changed in place) with the glyphs of buttons ({code point: Switch button}) drawn in a style: each new icon is scaled into the box of the glyph it
    replaces, centred on it, with the glyph's advance unchanged, so the game's text lays out as before. TrueType (glyf) and CFF outlines; the font's names stay, as the host finds the restyled font
    by the full name of the one the game loads (hle_sdk16.c icon_font_swap). Returns the code points changed"""
    I = Icons(letter_font, style, face); cm = font.getBestCmap(); gs = font.getGlyphSet(); done = []
    cff = font['CFF '].cff if 'CFF ' in font else None
    for cp, button in sorted(buttons.items()):
        gn = cm.get(cp)
        if gn is None: continue
        bp = BoundsPen(gs); gs[gn].draw(bp)
        if not bp.bounds: continue
        ox0, oy0, ox1, oy1 = bp.bounds
        draw, width = I.draw(button); rec = RecordingPen(); draw(rec, width / 2)
        nb = BoundsPen(None); rec.replay(nb); nx0, ny0, nx1, ny1 = nb.bounds
        s = min((ox1 - ox0) / (nx1 - nx0), (oy1 - oy0) / (ny1 - ny0))
        dx = (ox0 + ox1) / 2 - (nx0 + nx1) / 2 * s; dy = (oy0 + oy1) / 2 - (ny0 + ny1) / 2 * s
        adv = font['hmtx'][gn][0]
        if 'glyf' in font:
            pen = TTGlyphPen(gs); rec.replay(TransformPen(pen, (s, 0, 0, s, dx, dy)))
            g = pen.glyph(); g.recalcBounds(font['glyf']); font['glyf'][gn] = g
            font['hmtx'][gn] = (adv, g.xMin)
        elif cff is not None:
            td = cff.topDictIndex[0]; cs = td.CharStrings
            priv = td.FDArray[td.FDSelect[font.getGlyphID(gn)]].Private if hasattr(td, 'FDArray') else td.Private
            w = None if adv == getattr(priv, 'defaultWidthX', 0) else adv - getattr(priv, 'nominalWidthX', 0)
            pen = T2CharStringPen(w, gs); rec.replay(TransformPen(pen, (s, 0, 0, s, dx, dy)))
            new = pen.getCharString(private=priv, globalSubrs=cff.GlobalSubrs)
            cs[gn] = new
            font['hmtx'][gn] = (adv, round(dx + nx0 * s))
        else: raise ValueError('a font without glyf or CFF outlines')
        done.append(cp)
    return done

if __name__ == '__main__':
    if len(sys.argv) < 2: sys.exit('usage: make_ext_font.py out.ttf [letter-font.ttf]')
    build_all(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else LETTERS)
