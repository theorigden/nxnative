#!/usr/bin/env python3
"""A game's own button-icon font in the styles of other controllers (DM_BUTTON_ICONS; docs/reference/services.md, "Button icons of the player's controller").
Some games draw their button prompts with a font of their own instead of the system's Nintendo extension font (Tears of the Kingdom: RomFS Font/Font.Nin_NX_NVN.bfarc.zs › scft/External.bfotf,
A at U+E040). The profile's icon_font rows name that font and its buttons: icon_font <TAB> <RomFS path>[:<archive member>] <TAB> <code point>=<Switch button> ... (buttons as make_ext_font.Icons
draws them: A B X Y L R ZL ZR Plus Minus StickL StickR). For each style but the Switch's this writes the font with those glyphs redrawn (make_ext_font.restyle), into the shared-font folder as
game_<full name>_<variant>.ttf; the host serves it in place of the game's when the game loads a font of that full name (hle_sdk16.c icon_font_swap).
The font is read from the RomFS (an image or a folder): a .zs file is zstd (with the dictionaries of Pack/ZsDic.pack.zs when it needs one), an archive member is a SARC's, and a BFTTF / BFOTF is
de-obfuscated (8-byte header and per-word XOR); a plain TTF / OTF is taken as it is.
Usage: game_icon_font.py <RomFS image or folder> <out folder> [letter-font.ttf]   (DM_GAME picks the profile); needs fontTools and the zstd command"""
import io, os, re, struct, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', 'games'))
import make_ext_font as mef

BUTTONS = {'A', 'B', 'X', 'Y', 'L', 'R', 'ZL', 'ZR', 'Plus', 'Minus', 'StickL', 'StickR'}

def parse_rows(rows):   # icon_font rows → [(path, member or None, {code point: button})]
    out = []
    for r in rows:
        if len(r) < 2: raise ValueError(f'icon_font {r}: want <RomFS path>[:<member>] <TAB> <code point>=<button> ...')
        path, _, member = r[0].partition(':'); m = {}
        for w in r[1].split():
            cp, _, b = w.partition('=')
            if b not in BUTTONS: raise ValueError(f'icon_font: unknown button {b!r} (one of {" ".join(sorted(BUTTONS))})')
            m[int(cp, 16)] = b
        out.append((path, member or None, m))
    return out

class RomFS:
    def __init__(self, src):
        self.src = src; self.idx = None
        if os.path.isfile(src):
            import romfs_image
            self.idx = romfs_image.read_index(src)
    def read(self, path):
        if self.idx is None:
            with open(os.path.join(self.src, path), 'rb') as f: return f.read()
        d, off, size = self.idx[path]
        with open(self.src, 'rb') as f: f.seek(off); return f.read(size)
    def exists(self, path): return path in self.idx if self.idx is not None else os.path.isfile(os.path.join(self.src, path))

def zstd(data, dictionary=None):
    with tempfile.TemporaryDirectory() as d:
        cmd = ['zstd', '-q', '-d', '-c']
        if dictionary is not None:
            open(os.path.join(d, 'dict'), 'wb').write(dictionary); cmd += ['-D', os.path.join(d, 'dict')]
        r = subprocess.run(cmd, input=data, capture_output=True)
        return r.stdout if r.returncode == 0 else None

def sarc(data):   # {name: bytes} of a SARC archive (little-endian, as the Switch's)
    if data[:4] != b'SARC': raise ValueError('not a SARC archive')
    hl, _, _, doff = struct.unpack_from('<HHII', data, 4)
    o = hl; _, n, _ = struct.unpack_from('<HHI', data, o + 4); o += 12
    ents = [struct.unpack_from('<IIII', data, o + 16 * i) for i in range(n)]; o += 16 * n + 8
    out = {}
    for _, attr, s, e in ents:
        no = o + (attr & 0xffff) * 4; out[data[no:data.index(b'\0', no)].decode()] = data[doff + s:doff + e]
    return out

def zs_dicts(rom):   # the dictionaries of Pack/ZsDic.pack.zs (Nintendo EPD's games), zs.zsdic first
    if not rom.exists('Pack/ZsDic.pack.zs'): return []
    pack = zstd(rom.read('Pack/ZsDic.pack.zs'))
    if pack is None: return []
    d = sarc(pack); return [d[k] for k in sorted(d, key=lambda k: k != 'zs.zsdic')]

def unpack_zs(rom, data):
    out = zstd(data)
    for dic in ([] if out is not None else zs_dicts(rom)):
        out = zstd(data, dic)
        if out is not None: break
    if out is None: raise ValueError('zstd data that neither plain zstd nor a dictionary of Pack/ZsDic.pack.zs decodes')
    return out

def sfnt(data):   # the TTF / OTF of a BFTTF / BFOTF (its 8-byte header de-obfuscated gives the marker 0x7f9a0218 and the size), or of a plain font
    if data[:4] in (b'\0\1\0\0', b'OTTO', b'true'): return data
    key = struct.unpack_from('>I', data)[0] ^ 0x7f9a0218
    words = struct.unpack_from('>%dI' % (len(data) // 4), data)
    dec = struct.pack('>%dI' % len(words), *(w ^ key for w in words))
    n = struct.unpack_from('>I', dec, 4)[0]
    if dec[8:12] not in (b'\0\1\0\0', b'OTTO') or n > len(dec) - 8: raise ValueError('neither a TTF / OTF nor a BFTTF / BFOTF')
    return dec[8:8 + n]

def load(rom, path, member):
    data = rom.read(path)
    if path.endswith('.zs'): data = unpack_zs(rom, data)
    if member: data = sarc(data)[member]
    return sfnt(data)

def safe_name(name): return re.sub(r'[^A-Za-z0-9_-]', '_', name)   # as the host makes it (hle_sdk16.c icon_font_swap)

def build(romfs, out_dir, rows, letters=mef.LETTERS):
    from fontTools.ttLib import TTFont
    rom = RomFS(romfs); os.makedirs(out_dir, exist_ok=True); written = []
    for path, member, buttons in parse_rows(rows):
        data = load(rom, path, member)
        name = TTFont(io.BytesIO(data))['name'].getDebugName(4)
        for v, (style, face) in mef.VARIANTS.items():
            if not v: continue
            f = TTFont(io.BytesIO(data)); done = mef.restyle(f, buttons, style, face, letters)
            missing = sorted(set(buttons) - set(done))
            if missing: raise ValueError(f'{path}:{member}: no glyph at ' + ' '.join('U+%04X' % c for c in missing))
            out = os.path.join(out_dir, f'game_{safe_name(name)}_{v}.ttf'); f.save(out); written.append(out)
        print(f'{path}{":" + member if member else ""} ({name}): {len(buttons)} icons in {len(mef.VARIANTS) - 1} styles')
    return written

if __name__ == '__main__':
    if len(sys.argv) < 3: sys.exit(__doc__)
    import game
    g = game.load()
    rows = g.values('icon_font')
    if not rows: print(f'{g.id}: no icon_font rows (the game draws its button icons with the system font)'); sys.exit(0)
    build(sys.argv[1], sys.argv[2], rows, sys.argv[3] if len(sys.argv) > 3 else mef.LETTERS)
