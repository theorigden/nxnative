// The host tone map and HDR output (nvn_hdr.inc, included at the end of nvn_mtl.m): the roles a profile gives fragment shaders, and the hooks nvn_mtl.m calls
#pragma once
enum { HR_NONE, HR_TONEMAP, HR_EXPAND, HR_FINAL };   // NvShader.hdr_role: tonemap_agl (the host's tone map), hdr_expand (output scaled for HDR), hdr_final (the window copy)
#ifndef DM_GAME_TONEMAP_AGL   // a profile header from before these keys (test fixtures)
#define DM_GAME_TONEMAP_AGL ""
#define DM_GAME_HDR_EXPAND ""
#define DM_GAME_HDR_FINAL ""
#endif
static const int g_hdr_roles = sizeof(DM_GAME_TONEMAP_AGL) > 1 || sizeof(DM_GAME_HDR_EXPAND) > 1 || sizeof(DM_GAME_HDR_FINAL) > 1;   // the profile names any; 0: none of the hooks below run
static inline int pf_float(MTLPixelFormat f) { return f == MTLPixelFormatRG11B10Float || f == MTLPixelFormatRGBA16Float || f == MTLPixelFormatRGB9E5Float || f == MTLPixelFormatRGBA32Float; }   // a float picture (HDR presents it linear)
static int hdr_role_of(const char *key);   // the role of fragment shader key (16 hex digits, any suffix), from the profile's keys
static id<MTLLibrary> tm_host_lib(NSDictionary *j);   // the host's tone map library for a shader of that role, nil when its interface differs (it keeps the game's)
static const char *tm_mode_name(void);
static void tm_bind(id<MTLCommandEncoder> en);   // the grade block at fragment buffer TM_GRADE_BUFFER for a draw of the host's tone map
static int hdr_draw_begin(void);   // before a draw: 1 when it changed state hdr_draw_end restores
static void hdr_draw_end(void);
static const tex_t *hdr_present_swap(const tex_t *t, tex_t *tmp);   // a present of a window texture: the HDR copy of its picture when there is one
static id<MTLBuffer> hdr_probe_encode(id<MTL4CommandBuffer> cb, id<MTLTexture> drawable);   // DM_HDR_PROBE: the drawable read back, reported by hdr_probe_report
static void hdr_probe_report(id<MTLBuffer> b);
