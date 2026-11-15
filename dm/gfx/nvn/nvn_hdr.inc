// ---------- The host tone map and HDR output (included at the end of nvn_mtl.m; roles and hooks in nvn_hdr.h) ----------
// Three roles a profile gives fragment shaders by key (game.tsv tonemap_agl, hdr_expand, hdr_final; docs/reference/rendering.md, "Tone map and HDR by the host"):
//  - tonemap_agl: agl's tone map pass. The shader loader takes its function from the host's dm/gfx/msl/tonemap_agl.metal (the translated shader's interface, its maths written
//    out again) and the pass binds the grade block at fragment buffer TM_GRADE_BUFFER (tm_bind): the curve (the game's, bit for bit with the neutral grade; AgX; ACES), exposure,
//    contrast, saturation, the game's own saturation step, a black point, and for HDR the display's headroom over SDR white. The shader chain is untouched (DMSH_CHAIN).
//  - hdr_expand: the draws that carry the tone-mapped scene into the final image. The passes between them and the tone map (agl's FXAA, FSR 1's EASU) clamp to [0, 1], so for
//    HDR the tone map writes its picture divided by the headroom P, and these draws write theirs multiplied by P through the blender (source factor CONSTANT_COLOR = P, ZERO):
//    the scene reaches the final image in [0, P] while the HUD drawn after it stays at SDR white. Armed only after such a draw was seen in the last two frames, so a frame that
//    takes another route (no expansion) gets an SDR picture, not one divided by P.
//  - hdr_final: the draw that copies the final float image into the window texture (an RGBA8 texture through an sRGB view, which holds no value above 1). With HDR on, the host
//    copies that float image beside the window texture, once per frame, right before the draw (hdr_final_copy), and the present shows the copy (hdr_present_swap) on the
//    RGBA16Float extended linear layer the Mac front end sets up on an EDR screen (front_edr_headroom). Anything else that draws into the window texture after it drops the copy.
// Without EDR (DM_HDR off, a screen without headroom) the headroom is 1: the expansion is off and the window texture is presented as before.
#define TM_GRADE_BUFFER 27   // free in the fragment argument table: translated shaders bind buffer 0 there, and 28 to 30 (dmsh_abi.h); not in dmsh_abi.h, which is the chain's
typedef struct { uint32_t mode, look, game_sat, exact; float ev, s, peak, enc, contrast, sat, black, pad; } tm_grade_t;   // tonemap_agl.metal grade_t

static int keys_has(const char *list, const char *key) {   // list: 16-digit keys separated by commas; key: a shader key (16 hex digits and its route suffix)
    if (strlen(key) < 16) return 0;
    for (const char *q = list; *q; ) { size_t n = strcspn(q, ","); if (n == 16 && !strncmp(q, key, 16)) return 1; q += n; if (*q) q++; }
    return 0;
}
static int tm_enabled(void) { static int v = -1; if (v < 0) { const char *e = getenv("DM_TONEMAP"); v = !(e && !strcmp(e, "off")); if (!v) MLOG("tone map: DM_TONEMAP=off, the game's own shader"); } return v; }
static int hdr_role_of(const char *key) {
    if (!g_hdr_roles || !key) return HR_NONE;
    if (keys_has(DM_GAME_TONEMAP_AGL, key)) return tm_enabled() ? HR_TONEMAP : HR_NONE;
    if (keys_has(DM_GAME_HDR_EXPAND, key)) return HR_EXPAND;
    if (keys_has(DM_GAME_HDR_FINAL, key)) return HR_FINAL;
    return HR_NONE;
}
// The interface tonemap_agl.metal is written for: two textures with their samplers and twins, the driver constants and uniform buffer 0, the border block (agl's tone map as the
// chain translates it). Anything else keeps the game's shader
static id<MTLLibrary> tm_host_lib(NSDictionary *j) {
    static const char *want[] = {"c1", "cbuf", "tex", "samp_tex", "tex", "samp_tex", "samp_tex", "samp_tex", "border"};
    NSArray *b = j[@"bindings"]; int ok = [b isKindOfClass:NSArray.class] && b.count == 9 && [j[@"entry"] isEqual:@"main0"];
    for (NSUInteger i = 0; ok && i < 9; i++) ok = [b[i][@"arg_id"] intValue] == (int)i && [b[i][@"kind"] isEqual:@(want[i])];
    if (!ok) { RED_ONCE(176, "tone map: shader %s does not have agl's tone map interface (two textures, uniform buffer 0): the game's shader draws it", [j[@"key"] UTF8String]); return nil; }
    NSError *e = nil; id<MTLLibrary> lib = host_lib("tonemap_agl", &e);
    if (!lib) MLOG("[RED] tone map: the host's library did not load (%s): the game's shader draws it", e.localizedDescription.UTF8String);
    return lib;
}

// ---- The grade ----
static pthread_mutex_t g_grade_mu = PTHREAD_MUTEX_INITIALIZER;
static dm_grade g_grade; static int g_grade_init; static _Atomic uint64_t g_grade_gen;
static const char *k_curve_name[] = {"game", "agx", "aces"}, *k_look_name[] = {"none", "punchy", "golden"};
static float env_float(const char *name, const char *e, float def) { char *end; float v = e ? strtof(e, &end) : def; if (e && (end == e || *end)) { MLOG("[RED] %s=%s: not a number, %g", name, e, def); v = def; } return v; }
static int env_pick(const char *name, const char *e, const char **names, int n, int def) {
    if (!e || !*e) return def;
    for (int i = 0; i < n; i++) if (!strcmp(e, names[i])) return i;
    if (strcmp(e, "off")) MLOG("[RED] %s=%s: one of %s, %s%s%s; keeping %s", name, e, names[0], names[1], n > 2 ? ", " : "", n > 2 ? names[2] : "", names[def]);
    return def;
}
static dm_grade grade_clamp(dm_grade g) {
    g.curve = g.curve < 0 || g.curve > 2 ? 0 : g.curve; g.look = g.look < 0 || g.look > 2 ? 0 : g.look; g.game_sat = g.game_sat != 0;
    g.ev = fminf(fmaxf(g.ev, -8), 8); g.contrast = fminf(fmaxf(g.contrast, 0.25f), 4); g.saturation = fminf(fmaxf(g.saturation, 0), 4);
    g.black = fminf(fmaxf(g.black, -0.25f), 0.25f); g.peak = g.peak > 0 ? fminf(fmaxf(g.peak, 1), 64) : 0;
    return g;
}
static void grade_init_locked(void) {
    if (g_grade_init) return;
    g_grade_init = 1;
    g_grade = grade_clamp((dm_grade){env_pick("DM_TONEMAP", getenv("DM_TONEMAP"), k_curve_name, 3, 0), env_pick("DM_GRADE_LOOK", getenv("DM_GRADE_LOOK"), k_look_name, 3, 0),
                                     (int)env_float("DM_GRADE_GAME_SAT", getenv("DM_GRADE_GAME_SAT"), 1), env_float("DM_GRADE_EV", getenv("DM_GRADE_EV"), 0),
                                     env_float("DM_GRADE_CONTRAST", getenv("DM_GRADE_CONTRAST"), 1), env_float("DM_GRADE_SATURATION", getenv("DM_GRADE_SATURATION"), 1),
                                     env_float("DM_GRADE_BLACK", getenv("DM_GRADE_BLACK"), 0), env_float("DM_GRADE_PEAK", getenv("DM_GRADE_PEAK"), 0)});
}
void mtl_grade_get(dm_grade *g) { pthread_mutex_lock(&g_grade_mu); grade_init_locked(); *g = g_grade; pthread_mutex_unlock(&g_grade_mu); }
void mtl_grade_set(const dm_grade *g) {
    pthread_mutex_lock(&g_grade_mu); grade_init_locked(); g_grade = grade_clamp(*g); dm_grade v = g_grade; atomic_fetch_add(&g_grade_gen, 1); pthread_mutex_unlock(&g_grade_mu);
    MLOG("tone map: grade set: curve %s, look %s, game saturation %d, exposure %+.2f EV, contrast %.2f, saturation %.2f, black %.3f, peak %s%.1f", k_curve_name[v.curve], k_look_name[v.look],
         v.game_sat, v.ev, v.contrast, v.saturation, v.black, v.peak ? "" : "the display's, cap ", v.peak);
}
static const char *tm_mode_name(void) { dm_grade g; mtl_grade_get(&g); return k_curve_name[g.curve]; }

// The curves for a grey input, in double, as tonemap_agl.metal computes them (display-linear luminance): for the input scale that keeps 0.18 where the game's curve shows it
static double agx_grey(double x, int look) {
    static const double m[3][3] = {{0.842479062253094, 0.0784335999999992, 0.0792237451477643}, {0.0423282422610123, 0.878468636469772, 0.0791661274605434},
                                   {0.0423756549057051, 0.0784336, 0.879142973793104}};   // rows (the shader's columns transposed)
    static const double mi[3][3] = {{1.19687900512017, -0.0980208811401368, -0.0990297440797205}, {-0.0528968517574562, 1.15190312990417, -0.0989611768448433},
                                    {-0.0529716355144438, -0.0980434501171241, 1.15107367264116}};
    const double lo = -12.47393, hi = 4.026069; double v[3], w[3];
    for (int i = 0; i < 3; i++) { double a = (m[i][0] + m[i][1] + m[i][2]) * x; a = (fmin(fmax(log2(fmax(a, 1e-10)), lo), hi) - lo) / (hi - lo);
        double a2 = a * a, a4 = a2 * a2; v[i] = 15.5 * a4 * a2 - 40.14 * a4 * a + 31.96 * a4 - 6.868 * a2 * a + 0.4298 * a2 + 0.1191 * a - 0.00232; }
    if (look) { double luma = 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2], slope[3] = {1, look == 2 ? 0.9 : 1, look == 2 ? 0.5 : 1}, p = look == 2 ? 0.8 : 1.35, sat = look == 2 ? 0.8 : 1.4;
        for (int i = 0; i < 3; i++) v[i] = luma + sat * (pow(fmax(v[i] * slope[i], 0), p) - luma); }
    for (int i = 0; i < 3; i++) w[i] = pow(fmin(fmax(mi[i][0] * v[0] + mi[i][1] * v[1] + mi[i][2] * v[2], 0), 1), 2.2);
    return 0.2126 * w[0] + 0.7152 * w[1] + 0.0722 * w[2];
}
static double aces_grey(double x) { double v = (x * (x + 0.0245786) - 0.000090537) / (x * (0.983729 * x + 0.4329510) + 0.238081); return fmin(fmax(v, 0), 1); }   // both matrices keep grey
static double curve_grey(int mode, int look, double x) { return mode == 1 ? agx_grey(x, look) : mode == 2 ? aces_grey(x) : 1 - exp(-x); }
// s: peak * curve(s * 0.18) = 1 - exp(-0.18), the game curve's 0.18 in SDR. So AgX and ACES keep the game's exposure, and with headroom P a curve keeps its middle grey and
// reaches P instead of 1 (its toe stays close to SDR's, its shoulder moves up)
static double tm_scale(int mode, int look, double peak) {
    double want = (1 - exp(-0.18)) / peak;
    if (mode == 0) return peak == 1 ? 1 : -log1p(-want) / 0.18;
    double lo = log(1e-7), hi = log(1e6);
    for (int i = 0; i < 80; i++) { double m = (lo + hi) / 2; if (curve_grey(mode, look, exp(m)) < want) lo = m; else hi = m; }
    return exp((lo + hi) / 2) / 0.18;
}

// ---- HDR state, on the submit thread ----
__attribute__((weak)) float front_edr_headroom(void) { return 0; }   // the front end's (front.h): 0 without an EDR layer; none in the unit tests
static float g_tm_gain = 1;   // the factor the expansion draws apply: the headroom the last tone map pass divided by, 1 when not armed
static uint64_t g_hx_seen;    // the frame of the last expansion draw (g_cur_frame + 1, 0 = none)
static float hdr_peak(const dm_grade *g) { float h = front_edr_headroom(); if (h < 1) h = 1; if (g->peak > 0 && g->peak < h) h = g->peak; return h; }
static void tm_bind(id<MTLCommandEncoder> en) {
    static uint64_t gpu, pass, gen = ~0ull; static tm_grade_t last; static dm_grade g; static double s_key[3] = {-1}, s_val = 1; static int logged_armed = -1; static float logged_peak;
    uint64_t gg = atomic_load(&g_grade_gen); if (gg != gen) { mtl_grade_get(&g); gen = gg; }
    float p = hdr_peak(&g); uint64_t f = atomic_load(&g_cur_frame);
    int armed = p > 1.001f && g_hx_seen && g_hx_seen + 2 >= f + 1;
    float pe = armed ? p : 1;
    g_tm_gain = pe;
    if (s_key[0] != g.curve || s_key[1] != g.look || s_key[2] != pe) { s_key[0] = g.curve; s_key[1] = g.look; s_key[2] = pe; s_val = tm_scale(g.curve, g.look, pe); }
    tm_grade_t v = {(uint32_t)g.curve, (uint32_t)g.look, (uint32_t)g.game_sat, 0, exp2f(g.ev), (float)s_val, pe, 1 / pe, g.contrast, g.saturation, g.black, 0};
    v.exact = g.curve == 0 && pe == 1 && g.ev == 0 && g.contrast == 1 && g.saturation == 1 && g.black == 0 && g.game_sat;
    if (armed != logged_armed || fabsf(p - logged_peak) > 0.05f) { logged_armed = armed; logged_peak = p;
        MLOG("tone map: curve %s%s%s, input scale %.4f, %s", k_curve_name[g.curve], g.curve == 1 ? " look " : "", g.curve == 1 ? k_look_name[g.look] : "", s_val,
             armed ? [NSString stringWithFormat:@"HDR: peak %.2f x SDR white, the expansion draws scale by it", p].UTF8String : p > 1.001f ? "HDR: waiting for the expansion draws (SDR picture)" : "SDR"); }
    if (!gpu || pass != g_pass.serial || memcmp(&v, &last, sizeof v)) {
        __strong id<MTLBuffer> b; size_t off = arena_alloc(sizeof v, &b); memcpy((uint8_t *)b.contents + off, &v, sizeof v);
        gpu = b.gpuAddress + off; pass = g_pass.serial; last = v;
    }
    enc_r_args((id<MTL4RenderCommandEncoder>)en, MTLRenderStageFragment, gpu, TM_GRADE_BUFFER);
}

// The final image's copies, one per window texture, and the window textures presented lately (only those get copies)
enum { HFIN_N = 4 };
static struct { uint64_t win, ser; __strong id<MTLTexture> h; int armed; } g_hfin[HFIN_N];
static uint64_t g_hpres[HFIN_N]; static unsigned g_hpres_i; static int g_hfin_armed;
static void hfin_disarm(uint64_t win) { for (int k = 0; k < HFIN_N; k++) if (g_hfin[k].armed && g_hfin[k].win == win) { g_hfin[k].armed = 0; g_hfin_armed--; } }
static void hdr_final_copy(const tex_t *rt) {
    if (!rt || front_edr_headroom() < 1) return;
    uint64_t w = rt->serial; int known = 0;
    for (int i = 0; i < HFIN_N; i++) known |= g_hpres[i] == w;
    if (!known) return;
    int tid = (int)(tex_slot_h(S.tex[1], S.img[1], 0) & 0xfffff);
    os_unfair_lock_lock(&g_rmu); id<MTLTexture> f = tid ? tex_by_id(tid) : nil; os_unfair_lock_unlock(&g_rmu);
    if (!f || !pf_float(f.pixelFormat) || f.textureType != MTLTextureType2D || f.width != rt->d.width || f.height != rt->d.height) {
        RED_ONCE(174, "HDR: the final copy into window texture %llu reads no 2D float picture of its size (format %lu, %lux%lu): the window texture is presented",
                 (unsigned long long)w, (unsigned long)f.pixelFormat, (unsigned long)f.width, (unsigned long)f.height);
        return; }
    int k = 0;
    for (int i = 0; i < HFIN_N; i++) if (g_hfin[i].win == w) { k = i; goto found; }
    for (int i = 0; i < HFIN_N; i++) if (!g_hfin[i].win) { k = i; goto found; }
    k = (int)(w % HFIN_N);
found:
    if (!g_hfin[k].h || g_hfin[k].h.width != f.width || g_hfin[k].h.height != f.height || g_hfin[k].h.pixelFormat != f.pixelFormat) {
        if (g_hfin[k].ser) { if (g_hfin[k].armed) g_hfin_armed--; mtl_ext_tex_release(g_hfin[k].ser); }   // waits for the presents queued so far
        MTLTextureDescriptor *d = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:f.pixelFormat width:f.width height:f.height mipmapped:NO];
        d.storageMode = MTLStorageModePrivate; d.usage = MTLTextureUsageShaderRead;
        id<MTLTexture> h = [g_dev newTextureWithDescriptor:d]; h.label = @"HDR final image";
        if (!h) { RED_ONCE(175, "HDR: no texture for the final image's copy"); g_hfin[k].h = nil; g_hfin[k].ser = 0; g_hfin[k].win = 0; g_hfin[k].armed = 0; return; }
        g_hfin[k].h = h; g_hfin[k].ser = mtl_ext_tex((__bridge void *)h); g_hfin[k].armed = 0;
        MLOG("HDR: the final image (%lux%lu, format %lu) is copied beside window texture %llu and presented from there", (unsigned long)f.width, (unsigned long)f.height, (unsigned long)f.pixelFormat, (unsigned long long)w);
    }
    g_hfin[k].win = w;
    enc_b_copy_texture(blit(), f, 0, 0, MTLOriginMake(0, 0, 0), MTLSizeMake(f.width, f.height, 1), g_hfin[k].h, 0, 0, MTLOriginMake(0, 0, 0));
    if (!g_hfin[k].armed) g_hfin_armed++;
    g_hfin[k].armed = 1;
}
static const tex_t *hdr_present_swap(const tex_t *t, tex_t *tmp) {
    if (!g_hdr_roles || !t) return t;
    int known = 0; for (int i = 0; i < HFIN_N; i++) known |= g_hpres[i] == t->serial;
    if (!known) g_hpres[g_hpres_i++ % HFIN_N] = t->serial;
    for (int k = 0; k < HFIN_N; k++) if (g_hfin[k].armed && g_hfin[k].win == t->serial) {
        g_hfin[k].armed = 0; g_hfin_armed--;
        if (front_edr_headroom() < 1) return t;   // the window left its EDR screen since the copy
        memset(tmp, 0, sizeof *tmp); tmp->magic = MAGIC('T', 'E', 'X', 0); tmp->serial = g_hfin[k].ser;
        return tmp;
    }
    return t;
}
static struct { int on; blend_st b0; uint32_t en; float bc[4]; } g_hx_save;
static int hdr_draw_begin(void) {
    if (!S.prog) return 0;
    __unsafe_unretained NvProg *pr = prog_get(S.prog); __unsafe_unretained NvShader *fs = pr ? pr->sh[1] : nil;
    int role = fs ? fs->hdr_role : HR_NONE;
    const tex_t *rt = R.has_rt && R.rt.n > 0 ? R.rt.color[0] : NULL;
    if (role == HR_FINAL) { hdr_final_copy(rt); return 0; }
    if (g_hfin_armed && rt) hfin_disarm(rt->serial);   // anything else drawn into a window texture after its copy: that present shows the window texture
    if (role != HR_EXPAND) return 0;
    if (S.color.blend_en & 1) { static int n; if (!n++) MLOG("[RED] HDR: expansion draw %s blends itself: not scaled, the tone map stays SDR", fs->key); return 0; }
    g_hx_seen = atomic_load(&g_cur_frame) + 1;
    float gain = g_tm_gain;
    if (gain == 1) return 0;
    g_hx_save.b0 = S.blend[0]; g_hx_save.en = S.color.blend_en; memcpy(g_hx_save.bc, S.blend_color, sizeof g_hx_save.bc);
    S.blend[0] = (blend_st){.target = 0, .src_rgb = NVN_BLEND_FUNC_CONSTANT_COLOR, .dst_rgb = NVN_BLEND_FUNC_ZERO, .src_a = NVN_BLEND_FUNC_ONE, .dst_a = NVN_BLEND_FUNC_ZERO,
                            .eq_rgb = NVN_BLEND_EQUATION_ADD, .eq_a = NVN_BLEND_EQUATION_ADD};
    S.color.blend_en |= 1; S.blend_color[0] = S.blend_color[1] = S.blend_color[2] = gain; S.blend_color[3] = 1;
    g_pso_dirty = 1;
    return 1;
}
static void hdr_draw_end(void) {
    S.blend[0] = g_hx_save.b0; S.color.blend_en = g_hx_save.en; memcpy(S.blend_color, g_hx_save.bc, sizeof g_hx_save.bc);
    g_pso_dirty = 1;
}

// DM_HDR_PROBE=1 (diagnostic): every 300th present, the drawable is read back after the present pass and its largest and mean value logged with the layer's format, colour space
// and headroom: values above 1 there are what reaches the screen above SDR white (the front end makes the drawable readable for it)
static int hdr_probe_on(void) { static int v = -1; if (v < 0) { const char *e = getenv("DM_HDR_PROBE"); v = e && atoi(e) > 0; } return v; }
static id<MTLBuffer> hdr_probe_encode(id<MTL4CommandBuffer> cb, id<MTLTexture> dr) {
    static uint64_t n;
    if (!hdr_probe_on() || dr.framebufferOnly || (++n % 300) != 30) return nil;
    NSUInteger bpp = dr.pixelFormat == MTLPixelFormatRGBA16Float ? 8 : dr.pixelFormat == MTLPixelFormatBGRA8Unorm ? 4 : 0; if (!bpp) return nil;
    id<MTLBuffer> b = [g_dev newBufferWithLength:dr.width * dr.height * bpp options:MTLResourceStorageModeShared]; if (!b) return nil;
    res_add(b); res_commit();
    id<MTL4ComputeCommandEncoder> ce = [cb computeCommandEncoder];
    [ce barrierAfterQueueStages:MTLStageAll beforeStages:MTLStageBlit visibilityOptions:resource_vis()];
    [ce copyFromTexture:dr sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0) sourceSize:MTLSizeMake(dr.width, dr.height, 1) toBuffer:b destinationOffset:0
        destinationBytesPerRow:dr.width * bpp destinationBytesPerImage:dr.width * dr.height * bpp];
    [ce endEncoding];
    b.label = [NSString stringWithFormat:@"%lu %lu %lu", (unsigned long)dr.width, (unsigned long)dr.height, (unsigned long)dr.pixelFormat];
    return b;
}
static void hdr_probe_report(id<MTLBuffer> b) {   // the present's feedback handler
    unsigned long w = 0, h = 0, pf = 0; sscanf(b.label.UTF8String, "%lu %lu %lu", &w, &h, &pf);
    double mx = 0, sum = 0; uint64_t over = 0, n = (uint64_t)w * h;
    if (pf == MTLPixelFormatRGBA16Float) { const _Float16 *p = b.contents;
        for (uint64_t i = 0; i < n; i++) { double m = fmax(fmax((double)p[4 * i], (double)p[4 * i + 1]), (double)p[4 * i + 2]); mx = fmax(mx, m); sum += m; over += m > 1.0; } }
    else { const uint8_t *p = b.contents; for (uint64_t i = 0; i < n; i++) { double m = fmax(fmax(p[4 * i], p[4 * i + 1]), p[4 * i + 2]) / 255.0; mx = fmax(mx, m); sum += m; } }
    CAMetalLayer *l = (__bridge CAMetalLayer *)front_metal_layer();
    CFStringRef cs = l.colorspace ? CGColorSpaceGetName(l.colorspace) : NULL;
    MLOG("HDR probe: drawable %lux%lu format %lu (layer EDR %d, colour space %s, headroom %.2f): largest component %.3f, mean %.4f, pixels above SDR white %.2f %%", w, h, pf, l.wantsExtendedDynamicRangeContent,
         cs ? [(__bridge NSString *)cs UTF8String] : "none", front_edr_headroom(), mx, n ? sum / n : 0, n ? 100.0 * over / n : 0);
    res_remove(b); res_commit();
}
