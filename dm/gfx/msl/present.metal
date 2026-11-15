// The present: the frame drawn into the drawable, cropped (nvn_mtl.m present_pipeline)
#include <metal_stdlib>
using namespace metal;
struct V { float4 p [[position]]; float2 uv; };
vertex V vs(uint id [[vertex_id]]) { float2 uv = float2((id << 1) & 2, id & 2); V o; o.p = float4(uv * float2(2, -2) + float2(-1, 1), 0, 1); o.uv = uv; return o; }
struct Crop { float4 rect; float4 edge; };
fragment float4 fs(V in [[stage_in]], texture2d<float> t [[texture(0)]], sampler s [[sampler(0)]], constant Crop& c [[buffer(0)]]) { return t.sample(s, clamp(in.uv * c.rect.zw + c.rect.xy, c.edge.xy, c.edge.zw)); }
// HDR (nvn_hdr.inc): gamma bytes decoded for the extended linear RGBA16Float layer, where 1.0 is SDR white (fs_dec), and a float picture encoded to gamma bytes for the BGRA8Unorm layer (fs_enc)
static float3 srgb_dec(float3 c) { return select(pow((c + 0.055f) / 1.055f, 2.4f), c / 12.92f, c <= 0.04045f); }
static float3 srgb_enc(float3 c) { c = clamp(c, 0.0f, 1.0f); return select(1.055f * pow(c, 1.0f / 2.4f) - 0.055f, c * 12.92f, c <= 0.0031308f); }
fragment float4 fs_dec(V in [[stage_in]], texture2d<float> t [[texture(0)]], sampler s [[sampler(0)]], constant Crop& c [[buffer(0)]]) { return float4(srgb_dec(t.sample(s, clamp(in.uv * c.rect.zw + c.rect.xy, c.edge.xy, c.edge.zw)).rgb), 1); }
fragment float4 fs_enc(V in [[stage_in]], texture2d<float> t [[texture(0)]], sampler s [[sampler(0)]], constant Crop& c [[buffer(0)]]) { return float4(srgb_enc(t.sample(s, clamp(in.uv * c.rect.zw + c.rect.xy, c.edge.xy, c.edge.zw)).rgb), 1); }
