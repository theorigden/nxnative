// The host's replacement for agl's tone map pass (nvn_hdr.inc, a profile's tonemap_agl key: Tears of the Kingdom's 0ac9a54938974396): the translated shader's interface
// (argument buffer at buffer 0 with the same members and ids, the blend words at 28, varying locn0), its maths written out again, and a curve chosen each frame by the host's
// grade block at fragment buffer 27 (nvn_hdr.inc tm_grade_t, filled by tm_bind).
//   c = min(scene, 10000) + bloom (texture 0, texture 1); then
//   game:  the pass's own curve: L = dot(c, (0.2989, 0.5866, 0.1144)), e = 1 - exp(-c), eL = 1 - exp(-L), t = clamp(mix(c eL / L, e, eL^2), 0, 1),
//          and its saturation step out = M + (t - M)(U.x + U.y (1 - (S - 1)^2)), M = max(t), S = 2/3 (t.r + t.g + t.b), U = the game's uniform block (cbuf 0).
//          With the neutral grade (exact = 1) these are the translated shader's operations in its order, so the result is the game's to the bit (dm/gfx/tests/test_tonemap.py)
//   agx:   Troy Sobotka's AgX (the sRGB-primaries fit of its sigmoid), with the looks punchy and golden
//   aces:  Stephen Hill's fit of ACES's RRT and sRGB ODT, with its input and output matrices
// The grade, before the curve: exposure (ev), contrast about 0.18 by luminance, saturation; the curve's input scale s anchors 0.18 to the game curve's display value (host side);
// after it: the game's saturation step (game_sat), a black point, then peak (the display's EDR headroom, 1 in SDR) and enc (1 / peak while the HDR expansion is armed)
#include <metal_stdlib>
using namespace metal;

struct dm_border_t { uint mask; float4 k[32]; };
static inline __attribute__((always_inline)) float4 dm_bmix(float4 r, float4 w, float4 k) { return r + (w - r) * k; }
template<typename V, typename T, typename... A> static inline __attribute__((always_inline)) V dm_bs(V r, constant dm_border_t* b, uint i, T t, sampler w, A... a)
{
    if (b->mask >> i & 1u) r = dm_bmix(r, t.sample(w, a...), b->k[i]);
    return r;
}
struct dm_cb { float4 v[4096]; };
struct dm_args   // the translated shader's spvDescriptorSetBuffer0: the same members at the same ids
{
    constant dm_cb* c1 [[id(0)]];   // the driver's constants (0.5866, 0.1144, 2/3)
    constant dm_cb* c3 [[id(1)]];   // uniform buffer 0: the game's saturation weights U
    texture2d<float> scene [[id(2)]];
    sampler scene_s [[id(3)]];
    texture2d<float> bloom [[id(4)]];
    sampler bloom_s [[id(5)]];
    sampler scene_w [[id(6)]];
    sampler bloom_w [[id(7)]];
    constant dm_border_t* border [[id(8)]];
};
struct out_t { float4 c [[color(0)]]; };
struct in_t { float4 uv [[user(locn0)]]; };
struct dm_blend_state { uint zero; uint round; };
static inline __attribute__((always_inline)) float4 dm_bz(float4 c, uint m)
{
    m &= 3u;
    if (!((m == 1u && c.w == 0.0f) || (m == 2u && c.w == 1.0f))) return c;
    return float4(select(c.xyz, float3(0.0f), (as_type<uint3>(c.xyz) & uint3(0x7f800000u)) == uint3(0x7f800000u)), c.w);
}
static inline __attribute__((always_inline)) float4 dm_rop(float4 c, uint m)
{
    m &= 3u;
    if (m == 0u) return c;
    float4 s = m == 1u ? float4(255.0f) : (m == 2u ? float4(65535.0f) : float4(1023.0f, 1023.0f, 1023.0f, 3.0f));
    return rint(precise::clamp(c, 0.0f, 1.0f) * s) / s;
}
// The host's grade (nvn_hdr.inc tm_grade_t): mode 0 game, 1 agx, 2 aces; look 0 none, 1 punchy, 2 golden (agx); exact: the neutral grade on the game curve
struct grade_t { uint mode, look, game_sat, exact; float ev, s, peak, enc, contrast, sat, black, pad; };

static float3 game_curve(float3 c, constant dm_cb& k1)
{
    float L = fma(c.z, k1.v[0].y, fma(c.y, k1.v[0].x, c.x * 0.2989f));
    float eL = 1.0f - exp2(L * -1.44269502162933349609375f);
    float3 e = 1.0f - exp2(c * -1.44269502162933349609375f);
    float r = eL / L;
    return precise::clamp(fma(fma(c, float3(-r), e), float3(eL * eL), c * r), 0.0f, 1.0f);
}
static float3 agx_curve(float3 v, uint look)
{
    const float3x3 m = float3x3(float3(0.842479062253094f, 0.0423282422610123f, 0.0423756549057051f), float3(0.0784335999999992f, 0.878468636469772f, 0.0784336f),
                                float3(0.0792237451477643f, 0.0791661274605434f, 0.879142973793104f));
    const float3x3 mi = float3x3(float3(1.19687900512017f, -0.0528968517574562f, -0.0529716355144438f), float3(-0.0980208811401368f, 1.15190312990417f, -0.0980434501171241f),
                                 float3(-0.0990297440797205f, -0.0989611768448433f, 1.15107367264116f));
    const float lo = -12.47393f, hi = 4.026069f;
    v = m * v;
    v = (clamp(log2(max(v, 1e-10f)), lo, hi) - lo) / (hi - lo);
    float3 v2 = v * v, v4 = v2 * v2;
    v = 15.5f * v4 * v2 - 40.14f * v4 * v + 31.96f * v4 - 6.868f * v2 * v + 0.4298f * v2 + 0.1191f * v - 0.00232f;
    if (look) {
        float luma = dot(v, float3(0.2126f, 0.7152f, 0.0722f));
        float3 slope = look == 2 ? float3(1.0f, 0.9f, 0.5f) : float3(1.0f), power = float3(look == 2 ? 0.8f : 1.35f);
        float sat = look == 2 ? 0.8f : 1.4f;
        v = luma + sat * (pow(max(v * slope, 0.0f), power) - luma);
    }
    return pow(clamp(mi * v, 0.0f, 1.0f), 2.2f);
}
static float3 aces_curve(float3 v)
{
    const float3x3 in = float3x3(float3(0.59719f, 0.07600f, 0.02840f), float3(0.35458f, 0.90834f, 0.13383f), float3(0.04823f, 0.01566f, 0.83777f));
    const float3x3 out = float3x3(float3(1.60475f, -0.10208f, -0.00327f), float3(-0.53108f, 1.10813f, -0.07276f), float3(-0.07367f, -0.00605f, 1.07602f));
    v = in * v;
    v = (v * (v + 0.0245786f) - 0.000090537f) / (v * (0.983729f * v + 0.4329510f) + 0.238081f);
    return clamp(out * v, 0.0f, 1.0f);
}

fragment out_t main0(in_t in [[stage_in]], constant dm_args& a [[buffer(0)]], constant dm_blend_state& dm_blend [[buffer(28)]], constant grade_t& g [[buffer(27)]])
{
    out_t o = {};
    float2 uv = float2(in.uv.x, in.uv.y), q = select(uv, float2(0.0), isnan(uv));
    float3 sc = dm_bs(a.scene.sample(a.scene_s, q), a.border, 0u, a.scene, a.scene_w, q).xyz;
    float3 bl = dm_bs(a.bloom.sample(a.bloom_s, q), a.border, 1u, a.bloom, a.bloom_w, q).xyz;
    constant dm_cb& k1 = *a.c1; constant dm_cb& k3 = *a.c3;
    if (g.exact) {   // the translated shader's operations, in its order (its SSA names in the comments)
        float _69 = precise::min(sc.x, 10000.0) + bl.x, _71 = precise::min(sc.y, 10000.0) + bl.y, _73 = precise::min(sc.z, 10000.0) + bl.z;
        float _75 = _69 * 0.29890000820159912109375;
        float _77 = _69 * (-1.44269502162933349609375), _79 = _71 * (-1.44269502162933349609375);
        float _81 = fma(_71, k1.v[0].x, _75);
        float _83 = _73 * (-1.44269502162933349609375);
        float _85 = exp2(_79);
        float _87 = fma(_73, k1.v[0].y, _81);
        float _89 = 1.0 / _87;
        float _91 = _87 * (-1.44269502162933349609375);
        float _93 = exp2(_77), _95 = exp2(_91);
        float _99 = -_93 + 1.0, _103 = -_95 + 1.0;
        float _105 = exp2(_83);
        float _107 = _103 * _89;
        float _111 = -_85 + 1.0;
        float _113 = _103 * _103;
        float _117 = fma(_69, -_107, _99), _119 = _69 * _107;
        float _123 = -_105 + 1.0;
        float _127 = fma(_71, -_107, _111), _129 = _71 * _107;
        float _133 = precise::clamp(fma(_117, _113, _119), 0.0, 1.0);
        float _137 = fma(_73, -_107, _123), _139 = _73 * _107;
        float _143 = precise::clamp(fma(_127, _113, _129), 0.0, 1.0);
        float _145 = _133 * 0.666666686534881591796875;
        float _149 = precise::clamp(fma(_137, _113, _139), 0.0, 1.0);
        float _151 = fma(_143, k1.v[0].z, _145);
        uint _156 = max(max(as_type<uint>(_143), as_type<uint>(_149)), as_type<uint>(_133));
        float _158 = fma(_149, k1.v[0].z, _151);
        float m = as_type<float>(_156);
        float _172 = _158 + (-1.0);
        float _178 = fma(_172 * _172, -k3.v[0].y, k3.v[0].y);
        float _180 = _178 + k3.v[0].x;
        o.c = float4(fma(_133 + -m, _180, m), fma(_143 + -m, _180, m), fma(_149 + -m, _180, m), 0.0);
    } else {
        float3 c = max(precise::min(sc, 10000.0f) + bl, 0.0f) * g.ev;
        float L = dot(c, float3(0.2126f, 0.7152f, 0.0722f));
        if (g.contrast != 1.0f && L > 0.0f) c *= pow(L / 0.18f, g.contrast - 1.0f);
        if (g.sat != 1.0f) { L = dot(c, float3(0.2126f, 0.7152f, 0.0722f)); c = max(L + (c - L) * g.sat, 0.0f); }
        c *= g.s;
        float3 t = g.mode == 1 ? agx_curve(c, g.look) : g.mode == 2 ? aces_curve(c) : game_curve(c, k1);   // [0, 1]
        if (g.game_sat) {
            float m = max(max(t.x, t.y), t.z), S = fma(t.z, k1.v[0].z, fma(t.y, k1.v[0].z, t.x * 0.666666686534881591796875f)) - 1.0f;
            t = m + (t - m) * (fma(S * S, -k3.v[0].y, k3.v[0].y) + k3.v[0].x);
        }
        t *= g.peak;   // the display's headroom over SDR white (1 in SDR)
        if (g.black != 0.0f) t = max((t - g.black) / (1.0f - g.black), 0.0f);
        o.c = float4(max(t, 0.0f) * g.enc, 0.0f);
    }
    uint zm = dm_blend.zero, rm = dm_blend.round;
    if ((zm | rm) != 0u) o.c = dm_rop(dm_bz(o.c, zm), rm);
    return o;
}
