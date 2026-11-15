"""dm/tools/make_shared_fonts.py: each type's cut holds its characters only, carries no hinting (the font engine's interpreter memory grows with it) and no layout tables but kerning,
and takes a name of its own; the file names are the ones the host reads (hle_sdk16.c font_file). A small hinted source font is made here; with macOS's fonts the whole set is made too."""
import array
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
from typing import Any
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/tools'))
try:
    import fontTools   # noqa: F401
except ImportError:   # fontTools missing: the tool cannot run either
    raise unittest.SkipTest('fontTools is not installed') from None
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import ttProgram
import make_shared_fonts as msf


def cmap(f): return f.getBestCmap() or {}

# One character per set: Latin, kana, a GB 2312 hanzi (also cp932 and Big5), a GBK-only hanzi (also Big5), a Hangul syllable, and one in no set
CHARS = {'A': 0x41, 'a_kana': 0x3042, 'zhong': 0x4E2D, 'diu': 0x4E1F, 'ga': 0xAC00, 'arabic': 0x0627}

def source_font(path):   # hinted: fpgm, prep, cvt, a large stack and instructions on every glyph, as Arial Unicode has
    names = ['.notdef'] + list(CHARS)
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(names); fb.setupCharacterMap({cp: n for n, cp in CHARS.items()})
    glyphs = {}
    for n in names:
        pen = TTGlyphPen(None); pen.moveTo((100, 0)); pen.lineTo((100, 700)); pen.lineTo((500, 700)); pen.closePath()
        g = pen.glyph(); g.program = ttProgram.Program(); g.program.fromAssembly(['PUSHB[ ]', '0', 'POP[ ]']); glyphs[n] = g
    fb.setupGlyf(glyphs); fb.setupHorizontalMetrics({n: (600, 100) for n in names}); fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({'familyName': 'Source', 'styleName': 'Regular', 'fullName': 'Source', 'psName': 'Source'})
    fb.setupOS2(); fb.setupPost(); fb.setupMaxp()
    f = fb.font
    for tag, asm in (('fpgm', ['PUSHB[ ]', '0', 'FDEF[ ]', 'ENDF[ ]']), ('prep', ['PUSHB[ ]', '0', 'POP[ ]'])):   # fontTools' tables carry their fields dynamically: Any
        t: Any = newTable(tag); t.program = ttProgram.Program(); t.program.fromAssembly(asm); f[tag] = t
    cvt: Any = newTable('cvt '); cvt.values = array.array('h', [0, 10, 20]); f['cvt '] = cvt
    mx: Any = f['maxp']; mx.maxStackElements = 4139; mx.maxFunctionDefs = 1; mx.maxSizeOfInstructions = 3
    f.save(path)


class Cuts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.dir = Path(self.tmp.name)
        self.src = self.dir / 'source.ttf'; source_font(self.src)

    def tearDown(self): self.tmp.cleanup()

    def cut(self, t):
        name = dict((ty, nm) for ty, _, nm in msf.TYPES)[t]
        out = self.dir / f'{t}.ttf'
        msf.cut(str(self.src), str(out), msf.charsets()[t], name)
        return TTFont(out)

    def test_each_type_holds_its_characters_only(self):
        # GB 2312, Big5 and KS X 1001 hold kana too, and KS X 1001 hanja; the extension only what GBK adds to GB 2312; Arabic is in none
        want = {0: {'A', 'a_kana', 'zhong'}, 1: {'A', 'a_kana', 'zhong'}, 2: {'A', 'diu'}, 3: {'A', 'a_kana', 'zhong', 'diu'}, 4: {'A', 'a_kana', 'zhong', 'ga'}}
        for t, names in want.items():
            with self.subTest(type=t):
                have = cmap(self.cut(t))
                self.assertEqual({n for n, cp in CHARS.items() if cp in have}, names)

    def test_no_hinting_and_no_layout_tables_but_kerning(self):
        f = self.cut(0)
        for tag in ('fpgm', 'prep', 'cvt ', 'hdmx', 'VDMX', 'LTSH'): self.assertNotIn(tag, f)
        mx: Any = f['maxp']
        self.assertEqual((mx.maxStackElements, mx.maxSizeOfInstructions), (0, 0))
        self.assertFalse(any(getattr(f['glyf'][g], 'program', None) and f['glyf'][g].program.getBytecode() for g in f.getGlyphOrder()))

    def test_every_type_has_a_name_of_its_own(self):
        seen = set()
        for t, _, name in msf.TYPES:
            n = self.cut(t)['name']
            self.assertEqual((n.getDebugName(1), n.getDebugName(4), n.getDebugName(6)), (name, name, name.replace(' ', '-')))
            seen.add(name)
        self.assertEqual(len(seen), len(msf.TYPES))

    def test_file_names_are_the_hosts(self):
        src = (REPO / 'dm/host/hle_sdk16.c').read_text()
        m = re.search(r'font_file\[FONT_TYPES\] = \{([^}]*)\}', src)
        assert m, 'hle_sdk16.c font_file'
        self.assertEqual(re.findall(r'"([^"]+)"', m.group(1)), [fn for _, fn, _ in msf.TYPES] + [msf.EXT])


@unittest.skipIf(not (os.path.isfile(msf.SOURCE) and os.path.isfile(msf.LETTERS)), "macOS's Arial Unicode and Arial Rounded Bold")
class WholeSet(unittest.TestCase):
    def test_the_set_from_macos_fonts(self):
        with tempfile.TemporaryDirectory() as d:
            msf.build(d)
            names = set()
            for _, fn, _ in msf.TYPES + [(5, msf.EXT, '')]:
                f = TTFont(os.path.join(d, fn))
                self.assertNotIn('fpgm', f); self.assertNotIn('prep', f)
                names.add(f['name'].getDebugName(4))
            self.assertEqual(len(names), 6, 'six fonts, six full names (the name the font engine reports)')
            std = cmap(TTFont(os.path.join(d, 'standard.ttf')))
            for cp in (0x41, 0xE9, 0x416, 0x3042, 0x30A2, 0x6F22, 0xFF01): self.assertIn(cp, std)
            self.assertNotIn(0xAC00, std)
            self.assertIn(0xD7A3, cmap(TTFont(os.path.join(d, 'korean.ttf'))))


import make_ext_font as mef
import game_icon_font as gif


class IconStyles(unittest.TestCase):
    def test_the_icon_is_the_button_pressed(self):
        # by position the Switch's A is the right button (Xbox B), by label the bottom one (Xbox A); X and Y the same way
        self.assertEqual([mef.pad_button('xbox', 'position', b) for b in 'ABXY'], ['B', 'A', 'Y', 'X'])
        self.assertEqual([mef.pad_button('xbox', 'label', b) for b in 'ABXY'], ['A', 'B', 'X', 'Y'])
        self.assertEqual([mef.pad_button('playstation', 'position', b) for b in 'ABXY'], ['circle', 'cross', 'triangle', 'square'])
        self.assertEqual([mef.pad_button('playstation', 'label', b) for b in 'ABXY'], ['cross', 'circle', 'square', 'triangle'])

    def test_variants_are_the_hosts(self):
        src = (REPO / 'dm/host/button_icons.h').read_text()
        self.assertEqual(sorted(v for v in mef.VARIANTS if v), sorted(set(re.findall(r'"((?:xbox|playstation)[a-z_]*)"', src))))
        self.assertEqual(mef.variant_path('/f/nintendo_ext.ttf', 'xbox_label'), '/f/nintendo_ext_xbox_label.ttf')
        self.assertEqual(mef.variant_path('/f/nintendo_ext.ttf', ''), '/f/nintendo_ext.ttf')

    def test_icon_font_rows(self):
        rows = gif.parse_rows([['Font/F.bfarc.zs:scft/E.bfotf', 'E040=A E04B=Plus']])
        self.assertEqual(rows, [('Font/F.bfarc.zs', 'scft/E.bfotf', {0xE040: 'A', 0xE04B: 'Plus'})])
        with self.assertRaises(ValueError): gif.parse_rows([['F.ttf', 'E040=Home']])

    def test_obfuscated_font_in_a_sarc(self):
        font = b'OTTO' + bytes(range(60))
        key = 0x12345678
        plain = struct.pack('>II', 0x7f9a0218, len(font)) + font
        enc = b''.join(struct.pack('>I', struct.unpack_from('>I', plain, i)[0] ^ key) for i in range(0, len(plain), 4))
        self.assertEqual(gif.sfnt(enc), font)
        self.assertEqual(gif.sfnt(font), font)
        # a SARC with one member, as the Switch's (little-endian)
        name = b'scft/E.bfotf\0'; name += b'\0' * (-len(name) % 4)
        doff = 0x14 + 0xc + 0x10 + 8 + len(name)
        sarc = (b'SARC' + struct.pack('<HHII', 0x14, 0xfeff, doff + len(enc), doff) + b'\0\0\0\0' + b'SFAT' + struct.pack('<HHI', 0xc, 1, 0x65) +
                struct.pack('<IIII', 0, 0x01000000, 0, len(enc)) + b'SFNT' + struct.pack('<HH', 8, 0) + name + enc)
        self.assertEqual(gif.sfnt(gif.sarc(sarc)['scft/E.bfotf']), font)


def icon_font(path, cff):   # a game's icon font: a square glyph at U+E040 (A) and U+E041 (B), TrueType or CFF outlines
    names = ['.notdef', 'uniE040', 'uniE041']
    fb = FontBuilder(1000, isTTF=not cff)
    fb.setupGlyphOrder(names); fb.setupCharacterMap({0xE040: 'uniE040', 0xE041: 'uniE041'})
    def draw(pen): pen.moveTo((50, 20)); pen.lineTo((50, 620)); pen.lineTo((650, 620)); pen.lineTo((650, 20)); pen.closePath()
    if cff:
        from fontTools.pens.t2CharStringPen import T2CharStringPen
        cs = {}
        for n in names: p = T2CharStringPen(700, None); draw(p); cs[n] = p.getCharString()
        fb.setupCFF('Icons', {'FullName': 'Icons'}, cs, {})
    else:
        gl = {}
        for n in names: p = TTGlyphPen(None); draw(p); gl[n] = p.glyph()
        fb.setupGlyf(gl)
    fb.setupHorizontalMetrics({n: (700, 50) for n in names}); fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({'familyName': 'Icons', 'styleName': 'Regular', 'fullName': 'Icons', 'psName': 'Icons'})
    fb.setupOS2(); fb.setupPost(); fb.font.save(path)


@unittest.skipIf(not os.path.isfile(mef.LETTERS), "macOS's Arial Rounded Bold")
class Restyle(unittest.TestCase):
    def test_glyphs_redrawn_in_their_box(self):
        from fontTools.pens.boundsPen import BoundsPen
        for cff in (False, True):
            with self.subTest(cff=cff), tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, 'icons.otf'); icon_font(p, cff)
                f = TTFont(p)
                self.assertEqual(mef.restyle(f, {0xE040: 'A'}, 'xbox', 'position'), [0xE040])
                out = os.path.join(d, 'out.otf'); f.save(out); f = TTFont(out)
                gs = f.getGlyphSet(); a = BoundsPen(gs); gs['uniE040'].draw(a); b = BoundsPen(gs); gs['uniE041'].draw(b)
                from fontTools.pens.recordingPen import RecordingPen
                ra, rb = RecordingPen(), RecordingPen(); gs['uniE040'].draw(ra); gs['uniE041'].draw(rb)
                self.assertGreater(len(ra.value), 3 * len(rb.value), 'A redrawn (a disc with a letter), B left as it was (a square)')
                x0, y0, x1, y1 = a.bounds
                self.assertTrue(x0 >= 49 and y0 >= 19 and x1 <= 651 and y1 <= 621, a.bounds)
                self.assertEqual(f['hmtx']['uniE040'][0], 700)
                self.assertEqual(f['name'].getDebugName(4), 'Icons')

    def test_every_variant_of_the_extension_font(self):
        with tempfile.TemporaryDirectory() as d:
            mef.build_all(os.path.join(d, 'nintendo_ext.ttf'))
            self.assertEqual(sorted(os.listdir(d)), sorted(os.path.basename(mef.variant_path('nintendo_ext.ttf', v)) for v in mef.VARIANTS))
            for v in mef.VARIANTS:
                f = TTFont(os.path.join(d, os.path.basename(mef.variant_path('nintendo_ext.ttf', v))))
                self.assertEqual(f['name'].getDebugName(4), 'DM Nintendo Extension')
                self.assertEqual(f.getBestCmap()[0xE0E0], 'btnA')


if __name__ == '__main__':
    unittest.main()
