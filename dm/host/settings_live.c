// Settings a running game takes at once (settings_live.h): the in-game menus' live settings, applied where the host reads them while the game runs
#include "settings_live.h"
#include "dm.h"
#include "hle_haptics.h"
#include "../gfx/nvn/nvn_mtl.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

// Weak: the host's unit tests link the host without the graphics layer or the Apple rumble output; a setting whose reader is missing is not live
__attribute__((weak)) void mtl_grade_get(dm_grade *g);
__attribute__((weak)) void mtl_grade_set(const dm_grade *g);
__attribute__((weak)) void dm_haptics_apple_levels(float gain, float min);   // haptics_apple.m
__attribute__((weak)) float dm_render_scale_limit(void);                    // loader.c
__attribute__((weak)) int mtl_present_upscale_set(int on);                  // nvn_mtl.m
extern __attribute__((weak)) uint8_t *dm_fps_state;                         // loader.c: the frame step state page, NULL for a game without one

static int num(const char *v, float lo, float hi, float *out) {   // a number from lo to hi, as the launcher's ranges (no hex, no NaN)
    char *end; float x = strtof(v, &end);
    if (end == v || *end || strpbrk(v, "xX") || !(x >= lo && x <= hi)) return 0;
    *out = x; return 1;
}
static int pick(const char *v, const char *const *names, int n) { for (int i = 0; i < n; i++) if (!strcmp(v, names[i])) return i; return -1; }

#ifndef DM_GAME_TONEMAP_N   // a profile header from before the key (test fixtures)
#define DM_GAME_TONEMAP_N 0
#endif
static int grade_live(void) { return mtl_grade_get && mtl_grade_set && DM_GAME_TONEMAP_N != 0; }   // a profile that names its tone map pass (game.tsv tonemap_agl)
static int grade_apply(const char *env, const char *v) {
    static const char *const curves[] = {"game", "agx", "aces"}, *const looks[] = {"none", "punchy", "golden"};
    dm_grade g; mtl_grade_get(&g); float x; int i;
    if (!strcmp(env, "DM_TONEMAP")) { if ((i = pick(v, curves, 3)) < 0) return 0; g.curve = i; }   // "off" (the game's own shader) only at start: the pass's pipeline is chosen when its shader loads
    else if (!strcmp(env, "DM_GRADE_LOOK")) { if ((i = pick(v, looks, 3)) < 0) return 0; g.look = i; }
    else if (!strcmp(env, "DM_GRADE_GAME_SAT")) { if (strcmp(v, "0") && strcmp(v, "1")) return 0; g.game_sat = *v == '1'; }
    else if (!strcmp(env, "DM_GRADE_EV")) { if (!num(v, -8, 8, &x)) return 0; g.ev = x; }
    else if (!strcmp(env, "DM_GRADE_CONTRAST")) { if (!num(v, 0.25f, 4, &x)) return 0; g.contrast = x; }
    else if (!strcmp(env, "DM_GRADE_SATURATION")) { if (!num(v, 0, 4, &x)) return 0; g.saturation = x; }
    else if (!strcmp(env, "DM_GRADE_BLACK")) { if (!num(v, -0.25f, 0.25f, &x)) return 0; g.black = x; }
    else if (!strcmp(env, "DM_GRADE_PEAK")) { if (!num(v, 0, 64, &x)) return 0; g.peak = x; }
    else return 0;
    mtl_grade_set(&g);
    return 1;
}
static int is_grade(const char *env) {
    return !strcmp(env, "DM_TONEMAP") || !strncmp(env, "DM_GRADE_", 9);
}

int settings_live_apply(const char *env, const char *value) {
    if (!env) return 0;
    int ok = 0;
    if (is_grade(env)) {
        if (!grade_live()) return 0;
        if (!value) return 1;
        ok = grade_apply(env, value);
    } else if (!strcmp(env, "DM_FPS_TARGET")) {   // the frame step's cap, read at every present (hle_nvn.c fps_step_cap); a game without the state page reads its cap once
        if (!dm_fps_state) return 0;
        if (!value) return 1;
        if (strcmp(value, "30") && strcmp(value, "60")) return 0;   // 0 (the game's own interval) and 120 only at start
        float f = (float)atoi(value); __atomic_store((uint32_t *)dm_fps_state, (uint32_t *)&f, __ATOMIC_RELAXED);
        ok = 1;
    } else if (!strcmp(env, "DM_RENDER_SCALE")) {   // the render-scale stub multiplies each view's size by state +0x10 whenever the game sizes its views (patches.py)
        float hi = dm_fps_state && dm_render_scale_limit ? dm_render_scale_limit() : 0, x;
        if (hi <= 0) return 0;
        if (!value) return 1;
        if (!num(value, 0.5f, hi, &x)) return 0;
        __atomic_store((uint32_t *)(dm_fps_state + 0x10), (uint32_t *)&x, __ATOMIC_RELAXED);
        ok = 1;
    } else if (!strcmp(env, "DM_PRESENT_UPSCALE")) {   // the present's scaler, chosen at each present (nvn_mtl.m fx_encode)
        if (!mtl_present_upscale_set) return 0;
        if (!value) return 1;
        int on = !strcmp(value, "metalfx");
        if (!on && strcmp(value, "off")) return 0;
        ok = mtl_present_upscale_set(on);
    } else if (!strcmp(env, "DM_RUMBLE")) {
        if (!value) return 1;
        if (strcmp(value, "0") && strcmp(value, "1")) return 0;
        dm_haptics_set_enabled(*value == '1'); ok = 1;
    } else if (!strcmp(env, "DM_RUMBLE_GAIN") || !strcmp(env, "DM_RUMBLE_MIN")) {
        if (!dm_haptics_apple_levels) return 0;
        if (!value) return 1;
        int gain = env[10] == 'G'; float x;
        if (!num(value, 0, gain ? 3 : 0.9f, &x)) return 0;
        dm_haptics_apple_levels(gain ? x : -1, gain ? -1 : x); ok = 1;
    } else return 0;
    if (ok) { setenv(env, value, 1); LOG("settings: %s=%s applied while the game runs", env, value); }
    else LOG("[RED] settings: %s=%s is not a value this setting takes while the game runs; nothing changed", env, value);
    return ok;
}
