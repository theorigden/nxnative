"""The host's tone map (dm/gfx/msl/tonemap_agl.metal, nvn_hdr.inc; rendering.md, "Tone map and HDR by the host") on this Mac's GPU, drawn as the replay draws it (argument
buffer at 0, the blend words at 28, the grade block at 27, varying locn 0):
  - the general path with the game curve and the neutral grade against the exact path (the translated shader's operations, which were checked bit for bit against the
    game's own translated shader: 0 of 1,048,576 values differ), once both are stored as the R11G11B10F target stores them (no negative values);
  - each curve keeps 0.18 at the game curve's display value with the input scale tm_scale computes (ported here), in SDR and with HDR headroom 4, and reaches the peak;
  - with HDR armed (enc = 1 / peak) the output stays in [0, 1], the range agl's FXAA and FSR 1's EASU clamp to.
Skipped without the Metal toolchain."""
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SHADER = ROOT / 'dm/gfx/msl/tonemap_agl.metal'
INC = ROOT / 'dm/gfx/nvn/nvn_hdr.inc'

RUNNER = r'''
#import <Metal/Metal.h>
#include <stdio.h>
#include <stdlib.h>
typedef struct { uint32_t mode, look, game_sat, exact; float ev, s, peak, enc, contrast, sat, black, pad; } grade_t;
static const char *VS = "#include <metal_stdlib>\nusing namespace metal;\nstruct V { float4 p [[position]]; float4 uv [[user(locn0)]]; };\n"
    "vertex V vs(uint id [[vertex_id]]) { float2 uv = float2((id << 1) & 2, id & 2); V o; o.p = float4(uv * float2(2, -2) + float2(-1, 1), 0, 1); o.uv = float4(uv, 0, 0); return o; }\n";
// runner <metallib> <in.bin: W H then W*H*4 scene floats, W*H*4 bloom floats> <out.bin> mode look game_sat exact ev s peak enc
int main(int argc, char **argv) { @autoreleasepool {
    if (argc != 12) return 2;
    id<MTLDevice> d = MTLCreateSystemDefaultDevice(); id<MTLCommandQueue> q = [d newCommandQueue]; NSError *e;
    id<MTLLibrary> lb = [d newLibraryWithURL:[NSURL fileURLWithPath:@(argv[1])] error:&e], lv = [d newLibraryWithSource:@(VS) options:nil error:&e];
    if (!lb || !lv) { printf("library: %s\n", e.description.UTF8String); return 1; }
    FILE *f = fopen(argv[2], "rb"); uint32_t wh[2]; fread(wh, 4, 2, f); uint32_t W = wh[0], H = wh[1];
    float *sc = malloc(W * H * 16), *bl = malloc(W * H * 16); fread(sc, 16, W * H, f); fread(bl, 16, W * H, f); fclose(f);
    MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA32Float width:W height:H mipmapped:NO];
    id<MTLTexture> ts = [d newTextureWithDescriptor:td], tb = [d newTextureWithDescriptor:td];
    [ts replaceRegion:MTLRegionMake2D(0, 0, W, H) mipmapLevel:0 withBytes:sc bytesPerRow:W * 16]; [tb replaceRegion:MTLRegionMake2D(0, 0, W, H) mipmapLevel:0 withBytes:bl bytesPerRow:W * 16];
    MTLSamplerDescriptor *sd = [MTLSamplerDescriptor new]; sd.supportArgumentBuffers = YES; id<MTLSamplerState> ss = [d newSamplerStateWithDescriptor:sd];
    id<MTLBuffer> c1 = [d newBufferWithLength:65536 options:0], c3 = [d newBufferWithLength:65536 options:0], bord = [d newBufferWithLength:1024 options:0], z28 = [d newBufferWithLength:16 options:0];
    float k1[4] = {0.5866f, 0.1144f, 0.6666666865348816f, 0}, u[4] = {0.99f, 0.18f, 0.5f, 0}; memcpy(c1.contents, k1, 16); memcpy(c3.contents, u, 16);
    grade_t g = {atoi(argv[4]), atoi(argv[5]), atoi(argv[6]), atoi(argv[7]), atof(argv[8]), atof(argv[9]), atof(argv[10]), atof(argv[11]), 1, 1, 0, 0};
    id<MTLBuffer> gb = [d newBufferWithBytes:&g length:sizeof g options:0];
    id<MTLFunction> fn = [lb newFunctionWithName:@"main0"];
    MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new]; pd.vertexFunction = [lv newFunctionWithName:@"vs"]; pd.fragmentFunction = fn; pd.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA32Float;
    id<MTLRenderPipelineState> ps = [d newRenderPipelineStateWithDescriptor:pd error:&e]; if (!ps) { printf("pipeline: %s\n", e.description.UTF8String); return 1; }
    id<MTLArgumentEncoder> ae = [fn newArgumentEncoderWithBufferIndex:0]; id<MTLBuffer> ab = [d newBufferWithLength:ae.encodedLength options:0];
    [ae setArgumentBuffer:ab offset:0];
    [ae setBuffer:c1 offset:0 atIndex:0]; [ae setBuffer:c3 offset:0 atIndex:1]; [ae setTexture:ts atIndex:2]; [ae setSamplerState:ss atIndex:3]; [ae setTexture:tb atIndex:4]; [ae setSamplerState:ss atIndex:5];
    [ae setSamplerState:ss atIndex:6]; [ae setSamplerState:ss atIndex:7]; [ae setBuffer:bord offset:0 atIndex:8];
    td.usage = MTLTextureUsageRenderTarget; id<MTLTexture> out = [d newTextureWithDescriptor:td];
    MTLRenderPassDescriptor *rp = [MTLRenderPassDescriptor new]; rp.colorAttachments[0].texture = out; rp.colorAttachments[0].loadAction = MTLLoadActionClear; rp.colorAttachments[0].storeAction = MTLStoreActionStore;
    id<MTLCommandBuffer> cb = [q commandBuffer]; id<MTLRenderCommandEncoder> en = [cb renderCommandEncoderWithDescriptor:rp];
    [en setRenderPipelineState:ps]; [en setFragmentBuffer:ab offset:0 atIndex:0]; [en setFragmentBuffer:z28 offset:0 atIndex:28]; [en setFragmentBuffer:gb offset:0 atIndex:27];
    for (id<MTLResource> r in @[c1, c3, bord, ts, tb]) [en useResource:r usage:MTLResourceUsageRead stages:MTLRenderStageFragment];
    [en drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3]; [en endEncoding]; [cb commit]; [cb waitUntilCompleted];
    float *o = malloc(W * H * 16); [out getBytes:o bytesPerRow:W * 16 fromRegion:MTLRegionMake2D(0, 0, W, H) mipmapLevel:0];
    f = fopen(argv[3], "wb"); fwrite(o, 16, W * H, f); fclose(f);
    return 0;
} }
'''

# tm_scale and the curves for a grey input, as nvn_hdr.inc has them
AGX_M = [[0.842479062253094, 0.0784335999999992, 0.0792237451477643], [0.0423282422610123, 0.878468636469772, 0.0791661274605434], [0.0423756549057051, 0.0784336, 0.879142973793104]]
AGX_MI = [[1.19687900512017, -0.0980208811401368, -0.0990297440797205], [-0.0528968517574562, 1.15190312990417, -0.0989611768448433], [-0.0529716355144438, -0.0980434501171241, 1.15107367264116]]


def agx_grey(x, look):
    lo, hi = -12.47393, 4.026069
    v = []
    for row in AGX_M:
        a = (min(max(math.log2(max(sum(row) * x, 1e-10)), lo), hi) - lo) / (hi - lo)
        v.append(15.5 * a ** 6 - 40.14 * a ** 5 + 31.96 * a ** 4 - 6.868 * a ** 3 + 0.4298 * a ** 2 + 0.1191 * a - 0.00232)
    if look:
        luma = 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
        slope, p, sat = ([1, 0.9, 0.5], 0.8, 0.8) if look == 2 else ([1, 1, 1], 1.35, 1.4)
        v = [luma + sat * (max(v[i] * slope[i], 0) ** p - luma) for i in range(3)]
    w = [min(max(sum(r[j] * v[j] for j in range(3)), 0), 1) ** 2.2 for r in AGX_MI]
    return 0.2126 * w[0] + 0.7152 * w[1] + 0.0722 * w[2]


def curve_grey(mode, look, x):
    if mode == 1: return agx_grey(x, look)
    if mode == 2: return min(max((x * (x + 0.0245786) - 0.000090537) / (x * (0.983729 * x + 0.4329510) + 0.238081), 0), 1)
    return 1 - math.exp(-x)


def tm_scale(mode, look, peak):
    want = (1 - math.exp(-0.18)) / peak
    if mode == 0: return 1 if peak == 1 else -math.log1p(-want) / 0.18
    lo, hi = math.log(1e-7), math.log(1e6)
    for _ in range(80):
        m = (lo + hi) / 2
        if curve_grey(mode, look, math.exp(m)) < want: lo = m
        else: hi = m
    return math.exp((lo + hi) / 2) / 0.18


@unittest.skipUnless(shutil.which('xcrun') and subprocess.run(['xcrun', '-sdk', 'macosx', 'metal', '--version'], capture_output=True).returncode == 0, 'no Metal toolchain')
class TonemapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory(); t = Path(cls.td.name)
        cls.lib = t / 'tm.metallib'
        subprocess.run(['xcrun', '-sdk', 'macosx', 'metal', '-o', str(cls.lib), str(SHADER)], check=True)
        (t / 'r.m').write_text(RUNNER)
        cls.runner = t / 'runner'
        subprocess.run(['clang', '-fobjc-arc', '-framework', 'Metal', '-framework', 'Foundation', str(t / 'r.m'), '-o', str(cls.runner)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls): cls.td.cleanup()

    def draw(self, scene, bloom, mode=0, look=0, game_sat=1, exact=0, ev=1.0, s=1.0, peak=1.0, enc=1.0):
        """scene, bloom: lists of (r, g, b); one pixel each in a row"""
        t = Path(self.td.name); n = len(scene)
        with open(t / 'in.bin', 'wb') as f:
            f.write(struct.pack('<2I', n, 1))
            for px in scene: f.write(struct.pack('<4f', *px, 1))
            for px in bloom: f.write(struct.pack('<4f', *px, 1))
        r = subprocess.run([str(self.runner), str(self.lib), str(t / 'in.bin'), str(t / 'out.bin'), *map(str, (mode, look, game_sat, exact, ev, s, peak, enc))], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        o = (t / 'out.bin').read_bytes()
        return [struct.unpack_from('<4f', o, 16 * i)[:3] for i in range(n)]

    def test_general_game_curve_matches_the_exact_path(self):
        import random
        rnd = random.Random(7)
        def v(): return rnd.choice([0, rnd.random() * 0.01, rnd.random(), rnd.random() * 8, rnd.random() * 100, rnd.random() * 20000])
        scene = [(v(), v(), v()) for _ in range(4096)]; bloom = [(v() * 0.3, v() * 0.3, v() * 0.3) for _ in range(4096)]
        a = self.draw(scene, bloom, exact=1); b = self.draw(scene, bloom)
        worst = max(abs(max(x, 0) - y) for pa, pb in zip(a, b) for x, y in zip(pa, pb))   # the target stores no negative value
        self.assertLess(worst, 2e-5)

    def test_curves_keep_middle_grey_and_reach_the_peak(self):
        g0 = 1 - math.exp(-0.18)
        for mode, look in ((0, 0), (1, 0), (1, 1), (1, 2), (2, 0)):
            for peak in (1.0, 4.0):
                s = tm_scale(mode, look, peak)
                out = self.draw([(0.18, 0.18, 0.18), (1e5, 1e5, 1e5)], [(0, 0, 0)] * 2, mode=mode, look=look, game_sat=0, s=s, peak=peak)
                lum = 0.2126 * out[0][0] + 0.7152 * out[0][1] + 0.0722 * out[0][2]
                self.assertAlmostEqual(lum, g0, delta=0.004, msg=f'curve {mode} look {look} peak {peak}: 0.18 shows as {lum}')
                self.assertGreater(max(out[1]), peak * 0.95,   # the golden look tints white: its largest channel
                                   f'curve {mode} look {look} peak {peak}: the brightest value {out[1]}')

    def test_armed_hdr_output_stays_in_the_clamped_range(self):
        for mode in (0, 1, 2):
            s = tm_scale(mode, 0, 6.0)
            out = self.draw([(x, x * 0.5, x * 2) for x in (0.01, 0.18, 1, 10, 100, 1e4)], [(0, 0, 0)] * 6, mode=mode, s=s, peak=6.0, enc=1 / 6.0)
            self.assertLessEqual(max(max(p) for p in out), 1.0 + 1e-6, f'curve {mode}')

    def test_the_port_matches_nvn_hdr(self):   # the constants above are nvn_hdr.inc's
        src = INC.read_text()
        for c in ('-12.47393', '4.026069', '0.0245786', '0.000090537', '0.983729', '0.4329510', '0.238081', '1.35', '0.842479062253094', '1.15107367264116'):
            self.assertIn(c, src)


if __name__ == '__main__':
    unittest.main()
