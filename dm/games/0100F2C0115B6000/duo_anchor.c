// A screen taller than 16:9 (DM_SCREEN_ASPECT, Tears of the Kingdom 1.4.3): the HUD at the taller layout's edges. nn::ui2d's Pane: parent +0x18, child list +0x20 (first
// child at +0x28), translation +0x30, size +0x50, flags +0x58, global matrix 3x4 row-major +0x70 (scale +0x70 / +0x84, translation +0x7c / +0x8c).
// duo_calc runs from Pane::Calculate (main+0x593060) right after a pane's global matrix has been computed (the call to main+0x10d7538 returns to main+0x593110) and before
// its children's are, so what it does to a pane's matrix its children and text follow. The library recomputes a global matrix only when the pane or a parent changed, so a
// shift is added once per computation:
// - a full-screen background (a leaf that draws, as wide and as tall as its layout, centred) is stretched to the taller screen;
// - a widget at the layout's top or bottom edge moves out by the extra half-height with everything in it, so it sits at the screen's edge again; at the top it stops
//   short of a camera housing's row by the HUD's top inset (state +0x64, written by the Mac front end while the picture fills that row), so the HUD stays below it.
// Layouts placed by their root (markers over characters, set at a point of the 3D scene) are left alone.
// What draws is told by the vtable's DrawSelf (slot 28), which null panes, alignments, captures and parts keep from nn::ui2d::Pane (main+0x10d7f98, an empty function;
// fn_null_draw is its address).
// st: the parameters (state page + 0x80), in 720 units: st[0] the shift (layout half-height - 360; 0 = off), st[1] the vertical stretch (layout height / 720), st[2] the
// edge rule's distance (DM_SCREEN_HUD), st[3] unused here, st[4] / st[5] a full-screen pane's width / height, st[6] the tallest pane still stretched; st[-7] (state +0x64)
// the top inset in layout units. Compiled to position-independent code with no data (constants are immediates)
static inline float fab(float x) { return x < 0 ? -x : x; }
static inline float f(const char *p, int off) { return *(const float *)(p + off); }
static inline const char *parent(const char *p) { return *(const char *const *)(p + 0x18); }
static inline int draws(const char *p, const void *fn_null_draw) { return (*(const void *const *const *)p)[28] != fn_null_draw; }
static inline int moved(const char *p) { float tx = f(p, 0x30), ty = f(p, 0x34); return tx * tx + ty * ty > 0.25f; }
// a pane that only holds others: one that draws nothing and is smaller than 64 either way (null panes and alignments), or one as large as the layout
static inline int container(const char *p, const void *fn_null_draw, const float *st, float u) {
    float w = fab(f(p, 0x50) * f(p, 0x70)), h = fab(f(p, 0x54) * f(p, 0x84));
    if (w >= st[4] * u && h >= st[5] * u) return 1;
    return !draws(p, fn_null_draw) && (w < 64 * u || h < 64 * u);
}

void duo_calc(char *pane, const float *st, const void *fn_null_draw) {
    if (st[0] == 0) return;
    const char *pp = parent(pane);
    if (!pp) return;   // a layout's root
    // The layout's space: 1920x1080 or 1280x720 (the root pane's size); the parameters are in 720 units
    const char *root = pp;
    for (int i = 0; i < 48 && parent(root); i++) root = parent(root);
    float u = f(root, 0x54) >= 1000 ? 1.5f : 1.0f;
    float *g = (float *)(pane + 0x70);
    float gw = fab(f(pane, 0x50) * g[0]), gh = fab(f(pane, 0x54) * g[5]);
    int leaf = *(char *const *)(pane + 0x28) == pane + 0x20;   // the child list empty: a stretch would carry over to children (a menu page's whole content)
    if (gw >= st[4] * u && gh >= st[5] * u && gh <= st[6] * u && fab(g[3]) < 40 * u && fab(g[7]) < 40 * u) {
        if (leaf && draws(pane, fn_null_draw)) { g[4] *= st[1]; g[5] *= st[1]; g[6] *= st[1]; g[7] *= st[1]; }
        return;
    }
    // a background as tall as the layout but not as wide, centred up and down: stretched the same way
    if (leaf && gh >= st[5] * u && gh < 720 * u * st[1] - 2 && fab(g[7]) < 40 * u && draws(pane, fn_null_draw)) {
        g[4] *= st[1]; g[5] *= st[1]; g[6] *= st[1]; g[7] *= st[1];
        return;
    }
    // A widget is the topmost pane of its chain that is not a container
    if (container(pane, fn_null_draw, st, u)) return;
    const char *p = pp;
    for (int i = 0; i < 48; i++) {
        const char *par = parent(p);
        if (!par) { if (moved(p)) return; break; }   // p is the root: a layout placed by its root is not on the screen's edges
        if (!container(p, fn_null_draw, st, u)) return;   // a widget above: the widget's top is further up
        p = par;
    }
    float *gy = g + 7, in = st[-7];
    if (!(in > 0 && in < 2 * st[0])) in = 0;   // the top inset, within the extra height
    if (fab(*gy) >= st[2] * u) *gy += *gy > 0 ? (st[0] - in) * u : -st[0] * u;
}
