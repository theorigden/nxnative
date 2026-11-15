// Button icons of the player's controller (DM_BUTTON_ICONS; docs/reference/services.md, "Button icons of the player's controller"). Games draw their button prompts as glyphs of a font: the
// system's Nintendo extension font, which the host supplies (hle_sdk16.c, made by dm/tools/make_ext_font.py), or one of their own (the profile's icon_font, dm/tools/game_icon_font.py).
// Both are built in every style, one file per variant, and the host serves the variant of the controller the player uses: auto takes the style from the controller connected at start
// (front_pad_kind: Xbox or PlayStation, anything else the Switch's own icons); switch, xbox and playstation force one. An Xbox or PlayStation icon shows the button the player presses for
// the Switch button, so its variant follows DM_PAD_FACE: by position (the default) the Switch's A is the right button (Xbox B), with label the bottom one (Xbox A).
// Pure, so tests/t_shared_font.c checks the choice without a controller.
#pragma once
#include <stdio.h>
#include <string.h>

enum { BI_SWITCH, BI_XBOX, BI_PLAYSTATION };
// front_pad_kind's answers (front.h)
enum { PAD_KIND_LOOKING = -2, PAD_KIND_NONE = -1, PAD_KIND_OTHER = 0, PAD_KIND_XBOX = 1, PAD_KIND_PLAYSTATION = 2 };

// The style for a DM_BUTTON_ICONS value (NULL or empty: auto) and the controller's kind
static inline int bi_style(const char *setting, int pad_kind) {
    if (setting && !strcmp(setting, "switch")) return BI_SWITCH;
    if (setting && !strcmp(setting, "xbox")) return BI_XBOX;
    if (setting && !strcmp(setting, "playstation")) return BI_PLAYSTATION;
    return pad_kind == PAD_KIND_XBOX ? BI_XBOX : pad_kind == PAD_KIND_PLAYSTATION ? BI_PLAYSTATION : BI_SWITCH;
}
// The fonts' file suffix (make_ext_font.py VARIANTS): NULL for the Switch's own icons, else xbox, xbox_label, playstation or playstation_label. by_label: DM_PAD_FACE=label
static inline const char *bi_variant(int style, int by_label) {
    if (style == BI_XBOX) return by_label ? "xbox_label" : "xbox";
    if (style == BI_PLAYSTATION) return by_label ? "playstation_label" : "playstation";
    return NULL;
}
// A font file's name in a variant: nintendo_ext.ttf → nintendo_ext_xbox.ttf (the Switch's: as it is)
static inline void bi_file(char *out, size_t cap, const char *file, const char *variant) {
    const char *dot = strrchr(file, '.');
    if (!variant || !dot) { snprintf(out, cap, "%s", file); return; }
    snprintf(out, cap, "%.*s_%s%s", (int)(dot - file), file, variant, dot);
}
// The full name (name ID 4) of an sfnt font (TrueType or OpenType) in out, as dm/tools/game_icon_font.py safe_name has it (anything but letters, digits, _ and - as _), for the file of its
// restyled copy (game_<name>_<variant>.ttf). Windows (UTF-16BE, ASCII kept) or Mac Roman records. 0 when data is not a font or has no full name
static inline int bi_font_name(const unsigned char *d, size_t n, char *out, size_t cap) {
    #define BE16(p) ((unsigned)(p)[0] << 8 | (p)[1])
    #define BE32(p) ((unsigned)(p)[0] << 24 | (unsigned)(p)[1] << 16 | (unsigned)(p)[2] << 8 | (p)[3])
    if (!d || n < 12 || !cap) return 0;
    unsigned v = BE32(d);
    if (v != 0x00010000u && v != 0x4F54544Fu && v != 0x74727565u) return 0;   // 1.0, 'OTTO', 'true'
    unsigned nt = BE16(d + 4);
    for (unsigned i = 0; i < nt && 12 + 16 * (size_t)i + 16 <= n; i++) {
        const unsigned char *r = d + 12 + 16 * i;
        if (memcmp(r, "name", 4)) continue;
        size_t off = BE32(r + 8), len = BE32(r + 12);
        if (off + 6 > n || off + len > n) return 0;
        const unsigned char *t = d + off; unsigned count = BE16(t + 2); size_t sto = BE16(t + 4);
        for (int pass = 0; pass < 2; pass++)   // Windows first, then Mac
            for (unsigned k = 0; k < count && 6 + 12 * (size_t)k + 12 <= len; k++) {
                const unsigned char *e = t + 6 + 12 * k;
                unsigned plat = BE16(e), id = BE16(e + 6), sl = BE16(e + 8); size_t so = BE16(e + 10);
                if (id != 4 || plat != (pass ? 1u : 3u) || sto + so + sl > len) continue;
                const unsigned char *s = t + sto + so; size_t w = 0, step = pass ? 1 : 2;
                for (size_t j = 0; j + step <= sl && w + 1 < cap; j += step) {
                    unsigned c = pass ? s[j] : BE16(s + j);
                    out[w++] = (c < 128 && ((c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '_' || c == '-')) ? (char)c : '_';
                }
                out[w] = 0;
                if (w) return 1;
            }
        return 0;
    }
    return 0;
    #undef BE16
    #undef BE32
}
