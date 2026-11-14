# The Legend of Zelda: Tears of the Kingdom (0100F2C0115B6000): the rewriter's patches of this game's own builds. dm/tools/patch_nso.py loads every profile's patches.py and applies those of a module's NSO build ID;
# CUTS, OBS and FRAME_STEP as described there ("Registered patches"). Patches of Nintendo SDK module builds are in dm/tools/sdk_patches.py
import struct
from nso_asm import ADRP, B, NOP, STP_PRE

# Tears of the Kingdom picks a present interval each frame (main+0x2db174: 2 = 30 fps, 3 under load) and steps its game time by 60 / fps (int fps at timing +0x50, read at main+0x2daa54
# and main+0x3e562c). The stub replaces that logic: int fps = 60 / step, and the float fps (timing +0x24, unused, per masagrator's FPSLocker config for this build, which found the
# sites) the same, which the consumers read. Until the host has decided a step (the first frames) the step is the measured frame time (timing frame +0xd8, 19.2 MHz
# ticks), clamped to [1 / cap, 1 / 15 s]; game time that ran ahead after a short frame (the "lead", at most 0.25 s; totk-mobile) is paid back by later frames. Prerendered movies hold 30 (the host's movie flag, state +4, hle_movie.c
# dm_movie_playing), the D-pad menu fade starts at full rate (FPSLocker's fix at main+0x1fbc80) and the swapchain argument at main+0xbe14a8 becomes 1 as in FPSLocker
def frame_step(ctx):
    here, emit, fs_site, fs_put, FS_STATE_OFF = ctx.here, ctx.emit, ctx.site, ctx.put, ctx.state
    # frame step (replaces ldrb w9,[x0,#0x58], the first instruction after the prologue)
    fs_site(0x2db18c, '09604139')
    start = here(); emit(ADRP(16, here(), FS_STATE_OFF))
    for w in (0xbd400200,   # ldr s0,[x16]           target fps
              0x1e202008,   # fcmp s0,#0.0
              0x54000640,   # b.eq off (+50)        target 0: original path
              0xb9402202,   # ldr w2,[x16,#0x20]     step in vsyncs
              0x340001a2,   # cbz w2,elapsed (+13)   not decided yet: by the measured frame time
              0x1e230041,   # ucvtf s1,w2
              0x1e27d003,   # fmov s3,#30.0
              0x1e211872,   # fdiv s18,s3,s1
              0x1e322a52,   # fadd s18,s18,s18       fps = 60 / step
              0xbd002412,   # str s18,[x0,#0x24]     float fps
              0x52800785,   # mov w5,#60
              0x1ac208a5,   # udiv w5,w5,w2
              0xb9005005,   # str w5,[x0,#0x50]      integer fps
              0xf9401a04,   # ldr x4,[x16,#0x30]
              0x8b224084,   # add x4,x4,w2,uxtw
              0xf9001a04):  # str x4,[x16,#0x30]     vsyncs stepped
        emit(w)
    emit(B(here(), 0x2db284))                                       # the original epilogue
    for w in (0xf9406c22,   # elapsed: ldr x2,[x1,#0xd8]  last frame time in 19.2 MHz ticks
              0x9e630041,   # ucvtf d1,x2
              0x529f0003,   # mov w3,#0xf800
              0x72a02483,   # movk w3,#0x124,lsl #16 (19,200,000)
              0x1e630062,   # ucvtf d2,w3
              0x1e621821,   # fdiv d1,d1,d2          elapsed seconds
              0xb9400604,   # ldr w4,[x16,#4]        movie flag
              0x1e27d003,   # fmov s3,#30.0
              0x7100009f,   # cmp w4,#0
              0x1e201c60,   # fcsel s0,s3,s0,ne      cap = movie ? 30 : target
              0x1e22c000,   # fcvt d0,s0
              0x1e6e1003,   # fmov d3,#1.0
              0x1e601864,   # fdiv d4,d3,d0          shortest step 1 / cap
              0x1e65d005,   # fmov d5,#15.0
              0x1e651865,   # fdiv d5,d3,d5          longest step 1 / 15
              0xfd400606,   # ldr d6,[x16,#8]        lead
              0x1e663827,   # fsub d7,d1,d6
              0x1e6448e7,   # fmax d7,d7,d4
              0x1e6558e7,   # fmin d7,d7,d5          step = clamp(elapsed - lead)
              0x1e6728c6,   # fadd d6,d6,d7
              0x1e6138c6,   # fsub d6,d6,d1          lead += step - elapsed
              0x2f00e410,   # movi d16,#0
              0x1e7048c6,   # fmax d6,d6,d16
              0x1e6a1011,   # fmov d17,#0.25
              0x1e7158c6,   # fmin d6,d6,d17         lead in [0, 0.25]
              0xfd000606,   # str d6,[x16,#8]
              0x1e671872,   # fdiv d18,d3,d7         fps = 1 / step
              0x1e624252,   # fcvt s18,d18
              0xbd002412,   # str s18,[x0,#0x24]     float fps
              0x1e380245,   # fcvtzs w5,s18
              0xb9005005,   # str w5,[x0,#0x50]      integer fps
              0xfd400e13,   # ldr d19,[x16,#0x18]
              0x1e672a73,   # fadd d19,d19,d7
              0xfd000e13):  # str d19,[x16,#0x18]    game seconds stepped
        emit(w)
    emit(B(here(), 0x2db284))                                       # the original epilogue
    emit(0x39416009); emit(B(here(), 0x2db190))                     # off: ldrb w9,[x0,#0x58]; back
    fs_put(0x2db18c, [B(0x2db18c, start)], 'frame step from the host in whole vsyncs, by elapsed time until it has decided one (state page target fps; 0 = original interval logic)')
    # the two readers of the integer fps: float fps when on; the scvtf a few instructions later moves into the stub (s0 is not touched in between)
    for site, cvt, r in ((0x2daa54, 0x2daa6c, 19), (0x3e562c, 0x3e5638, 22)):
        fs_site(site, struct.pack('<I', 0xbd425000 | r << 5).hex()); fs_site(cvt, '00d8215e')
        start = here(); emit(STP_PRE(16, 17, 31, -16)); emit(ADRP(16, here(), FS_STATE_OFF))
        for w in (0xb9400211,                # ldr w17,[x16]
                  0x34000071,                # cbz w17,off (+12)
                  0xbd422400 | r << 5,       # ldr s0,[xR,#0x224]  float fps
                  0x14000003,                # b done (+12)
                  0xbd425000 | r << 5,       # off: ldr s0,[xR,#0x250]  integer fps
                  0x5e21d800,                # scvtf s0,s0
                  0xa8c147f0):               # done: ldp x16,x17,[sp],#16
            emit(w)
        emit(B(here(), site + 4))
        fs_put(site, [B(site, start)], 'game step reads the float fps (original integer fps and scvtf when off)')
        fs_put(cvt, [NOP], 'scvtf moved into the stub at the load')
    # D-pad menu fade (w8 is overwritten right after the site)
    fs_site(0x1fbc80, '0820201e0a04081f')
    start = here(); emit(ADRP(8, here(), FS_STATE_OFF))
    for w in (0xb9400108, 0x340001a8,       # ldr w8,[x8]; cbz w8,off (+52)
              0x1e202028, 0x54000101,       # fcmp s1,#0.0; b.ne go
              0x785fa308, 0x7100151f, 0x540000a1,   # ldurh w8,[x24,#-6]; cmp w8,#5; b.ne go
              0x785f8308, 0x7100151f, 0x54000041,   # ldurh w8,[x24,#-8]; cmp w8,#5; b.ne go
              0x1e2e1008,                   # fmov s8,#1.0
              0x1f08040a, 0x1e202008, 0x14000003,   # go: fmadd s10,s0,s8,s1; fcmp s0,#0.0; b end
              0x1e202008, 0x1f08040a):      # off: the original fcmp s0,#0.0; fmadd s10,s0,s8,s1
        emit(w)
    emit(B(here(), 0x1fbc88))
    fs_put(0x1fbc80, [B(0x1fbc80, start), NOP], 'D-pad menu fade starts at full rate under fractional steps (FPSLocker)')
    # swapchain argument (x16 is dead before the bl that follows)
    fs_site(0xbe14a8, '61a24039')
    start = here(); emit(ADRP(16, here(), FS_STATE_OFF))
    for w in (0xb9400210, 0x34000070, 0x52800021, 0x14000002, 0x3940a261):   # ldr w16,[x16]; cbz w16,off; mov w1,#1; b end; off: ldrb w1,[x19,#0x28]
        emit(w)
    emit(B(here(), 0xbe14ac))
    fs_put(0xbe14a8, [B(0xbe14a8, start)], 'swapchain argument 1 when on (FPSLocker)')
    # Render scale (state +0x10, float written by the loader: DM_RENDER_SCALE, 1.0 by default). main+0xd5c24 sizes each view: screen size x the view's scale (5/6 for the scene: 1600x896
    # docked) x the dynamic-resolution multiplier, clamped to 8..16384 and floored to the view's alignment. The stub multiplies both extents by the factor (s6, w8 and the flags are dead
    # at main+0xd5cc0: s6 is set to 8.0 right after); any factor but 1.0 also replaces the dynamic multiplier (main+0xd5d80) with 1, so the size is fixed. 1.0 = bit-exact original
    fs_site(0xd5cc0, '08d0a8524008251e6108241e0401271e'); fs_site(0xd5d80, '062940bd')
    start = here(); emit(ADRP(8, here(), FS_STATE_OFF))
    for w in (0xbd401106,   # ldr s6,[x8,#0x10]   render scale
              0x1e250840,   # fmul s0,s2,s5       (original)
              0x1e240861,   # fmul s1,s3,s4       (original)
              0x1e2020c8,   # fcmp s6,#0.0
              0x5400006d,   # b.le skip (+12)     not set
              0x1e260800,   # fmul s0,s0,s6
              0x1e260821,   # fmul s1,s1,s6
              0x52a8d008,   # skip: mov w8,#0x46800000 (original)
              0x1e270104):  # fmov s4,w8          (original)
        emit(w)
    emit(B(here(), 0xd5cd0))
    fs_put(0xd5cc0, [B(0xd5cc0, start)], 'view render size x the host render scale (1.0 = original)'); ctx.render_scale = 1
    start = here(); emit(0xbd402906); emit(ADRP(8, here(), FS_STATE_OFF))   # ldr s6,[x8,#0x28] (original: the dynamic multiplier); x8 is dead after it
    for w in (0xbd401107,   # ldr s7,[x8,#0x10]
              0x1e2e1010,   # fmov s16,#1.0
              0x1e3020e0,   # fcmp s7,s16
              0x54000080,   # b.eq done (+16)     scale 1: the game's dynamic resolution
              0x1e2020e8,   # fcmp s7,#0.0
              0x5400004d,   # b.le done (+8)      not set
              0x1e204206):  # fmov s6,s16         a fixed scale: no dynamic multiplier
        emit(w)
    emit(B(here(), 0xd5d84))
    fs_put(0xd5d80, [B(0xd5d80, start)], 'dynamic resolution only at render scale 1.0')
    screen_shape(ctx)

# Screen shape: a screen taller than 16:9 (a MacBook's 1.55:1, an iPad's 4:3; DM_SCREEN_ASPECT) gets a picture of its own shape, and a larger output (state +0x68 output
# width, 0 = 1920) a picture of that size. nnMain stores the display size, 1920x1080 (main+0xbdb578 / main+0xbdb584, stored at main+0xbdb588), which the framework takes
# for the logical frame buffer's physical size and the window textures, and passes (1280.0, 720.0) (main+0xbdb6a0) for its virtual (layout) size. The 3D views follow the
# frame buffer's width only (main+0xd5c24 x one uniform scale), so a taller output gives taller views (1600x1040 docked at 1.55:1). The presented picture is chosen by
# nvnWindowSetCrop from the display object's request (main+0x3de5a8 writes it: +0xac x, y, +0xb4 w, h), which the display-mode object fills with 1920x1080 docked: a
# docked crop of 1920x1080 becomes the output's size. Handheld (1280x720) keeps its crop: the screen shape is for docked mode. x16 is free in nnMain; main+0x3de5b8 is in a leaf.
# The field of view and the HUD's projection: sead::PerspectiveProjection is laid out as in Breath of the Wild 1.9.0 and its setFovy_, constructor, set() and doUpdateMatrix
# match it instruction for instruction at the sites, so its stub bodies are used as they are (01007EF00011E000/patches.py, which describes them; state +0x58.. and the
# ring of fovys at +0xfc..). The HUD at the taller edges: duo_anchor.c from nn::ui2d::Pane::Calculate (main+0x593110)
_duo_anchor = 'bd4000201e20200854000041d65f03c0f9400c08b4ffffc852800609aa0803eaf9400d4bb400008baa0b03ea7100052954ffff81bd40554152a88f491e2701221e2220201e2e10011e2f10021e21ac41bd4070022d4a14031e2208641e2288621e2020881e244c44bd4084031e2308a21e2388a51e2020481e224ca5f94014099100800abd4010221e2208221e222080540003cbbd4014261e2608261e2620a05400034bbd4018261e2608261e2620a0540002c8bd407c061e20c0c652a8440b1e2701671e2708271e2720c0540001e5bd408c061e20c0d01e27220054000165eb0a013f54fff941f9400008f9407108eb02011f54fff8c0bd400420bd4080011e2108001400001ceb0a013f540004c1bd4014261e2608261e2620a05400044b52a886891e2701261e260826bd4004271e3010101f0740c61e2620a054000345bd408c061e20c0d052a844091e2701311e3108311e31220054000265f9400009f9407129eb02013f540001e0bd4080001e2008e0bd008000bd4004201e200860bd008400bd400420bd4088011e210800bd008800bd4004201e2008c0bd008c00d65f03c01e222080540000abbd4014231e2308231e2320a054fff2aaf9400009f940712952a8500a1e2701431e230823eb02013f540000811e2320801e2354a854fff1645280060914000004aa0a03e87100052954000440f9400d0ab400034abd4071042d4a19051e2408a71e2488a41e2020e81e274c84bd4085051e2508c71e2588c51e2020e81e274ca51e222080540000abbd4014261e2608261e2620a054fffd6af9400108f9407108eb02011f54ffede11e2320801e2354a854fffc8417ffff6b2d460d021e2308631f020c421e2a10031e23204054ffecacbd408c021e20c043bd4008241e2408241e24206054ffebebbc5e40231e2028041e2420606f00e4041e2444641e24cc631e2338031e2140001e2020481e20cc601e2008201e202840bd008c00d65f03c0'
_duo_calc = 0x0
_pane_draw_self = 0x10d7f98   # nn::ui2d::Pane::DrawSelf (vtable main+0x357f280 slot 28, empty)
TANF, ATANF = 0x2bb7470, 0x2bb7480   # PLT
def _bl(frm, to): return 0x94000000 | (((to - frm) >> 2) & 0x3FFFFFF)
def screen_shape(ctx):
    here, emit, fs_site, fs_put, STATE = ctx.here, ctx.emit, ctx.site, ctx.put, ctx.state
    def stub(site, orig, body, why):
        fs_site(site, orig)
        start = here()
        for w in body:
            emit(ADRP(16, here(), STATE) if w is None else w)
        emit(B(here(), site + 4))
        fs_put(site, [B(site, start)], why)
    # display size: x8 = 1920 | 1080 << 32 → the host's height (+0x48) and width (+0x68) where set
    stub(0xbdb584, '0887c0f2', (0xf2c08708, None, 0xb9404a10, 0x34000050, 0xb3607e08, None, 0xb9406a10, 0x34000050, 0xb3407e08),
         'display size 1920x1080 (window textures, frame buffer) → the host\'s output size')
    # layout size: x8 = 1280.0 | 720.0 << 32 → the host's layout height (+0x50, float)
    stub(0xbdb6a0, '8886e8f2', (0xf2e88688, None, 0xb9405210, 0x34000050, 0xb3607e08),
         'layout size 1280x720 → the host\'s layout height')
    # crop request: a 1920x1080 crop becomes the output's size
    stub(0x3de5b8, '03901629', (None, 0xb9404a11, 0x34000131, 0x7110e09f, 0x540000e1, 0x711e007f, 0x540000a1, 0x2a1103e4, 0xb9406a11, 0x34000051, 0x2a1103e3,
                                0x29169003),
         'window crop 1920x1080 → the host\'s output size')
    FOV_BODY = (None, 0xbd405a01, 0x1e202028, 0x540003e0, 'ratio', 0x1e213842, 0x1e20c042, 0xbd406203, 0x1e232040, 0x5400032a,
                0xb940a269, 0x9104020a, 0x5280080b, 0xb840454c, 0x6b09019f, 0x54000260, 0x7100056b, 0x54ffff81,
                'half_to_s0', 'tanf', None, 0xbd405e01, 0x1e210800, 'atanf', 's0_to_half', 0x1e202800, 0xbd00a260,
                None, 0xb940fe0b, 0x1200156c, 0x1100056b, 0xb900fe0b, 0x9104020a, 0xbc2c5940, 'half_to_s0')
    def fov_stub(site, orig, aspect_word, half_to_s0, s0_to_half):
        fs_site(site, orig)
        start = here()
        for w in FOV_BODY:
            if w is None: emit(ADRP(16, here(), STATE))
            elif w == 'tanf': emit(_bl(here(), TANF))
            elif w == 'atanf': emit(_bl(here(), ATANF))
            else: emit({'ratio': aspect_word, 'half_to_s0': half_to_s0, 's0_to_half': s0_to_half}.get(w, w))
        emit(B(here(), site + 4))
        fs_put(site, [B(site, start)], 'sead::PerspectiveProjection fovy widened for a view of the screen\'s ratio (more above and below, 16:9 sides), stored widened')
    fov_stub(0x27d53f8, '0041201e', 0xbd40b262, 0x1e204100, 0x1e204008)   # setFovy_: ratio at [x19,#0xb0], half in s8
    fov_stub(0xc02694, '0041201e', 0xbd40b262, 0x1e204100, 0x1e204008)    # constructor: the same
    fov_stub(0xd4275c, '2041201e', 0x1e204102, 0x1e204120, 0x1e204009)    # set(): ratio in s8 (stored after), half in s9
    stub(0x27d5444, '0188552d', (0x2d558801, None,
         0xbd405a10, 0x1e202208, 0x54000320, 0xbd407611, 0x1e313851, 0x1e20c231, 0xbd407a12, 0x1e322220, 0x5400026a,
         0x2d534811, 0x1e2e1013, 0x1e332220, 0x540001e1, 0xbd407e13, 0x1e332240, 0x54000181,
         0x1e204202,
         0xb940a009, 0x9104020a, 0x5280080b, 0xb840454c, 0x6b09019f, 0x540000a0, 0x7100056b, 0x54ffff81,
         0xbd405e11, 0x1e310821),
         'PerspectiveProjection matrix: the HUD camera (16:9, near 1, far 10000) takes the screen\'s ratio and a widened vertical angle')
    # duo_calc(pane, state + 0x80, Pane::DrawSelf) after the global matrix, while the output's height is set. x0..x18 are dead at the site (x19 the pane)
    code = here()
    for i in range(0, len(_duo_anchor), 8): emit(int(_duo_anchor[i:i + 8], 16))
    fs_site(0x593110, '68624139')
    start = here(); emit(ADRP(16, here(), STATE))
    emit(0xb9404a11)   # ldr w17, [x16, #0x48]   the output's height (0 = 16:9)
    emit(0x340000d1)   # cbz w17, orig (+6)
    emit(0xaa1303e0)   # mov x0, x19
    emit(0x91020201)   # add x1, x16, #0x80
    emit(ADRP(2, here(), _pane_draw_self)); emit(0x91000042 | ((_pane_draw_self & 0xFFF) << 10))
    emit(_bl(here(), code + _duo_calc))
    emit(0x39416268)   # orig: ldrb w8, [x19, #0x58]
    emit(B(here(), 0x593114))
    fs_put(0x593110, [B(0x593110, start)], 'nn::ui2d::Pane::Calculate after the global matrix: duo_calc (the HUD at the taller screen\'s edges, below a camera housing\'s row)')

FRAME_STEP = {'277178b7dba1b6d4949a84778d4abc58': frame_step}

# How general each patch is and could be (dm/tools/docs_patches.py "Binding", listed in docs/agents/game-patches.md): what, its binding now, the loosest it could have (goal),
# purpose, why; blocked or kept: why the gap stays open (cannot close yet, or left open on purpose); checked: what was checked on game files (else a judgement)
BINDING = [
    {'what': '60 fps frame step and render scale', 'now': 'build', 'goal': 'game', 'purpose': 'frame rate',
     'why': "the game's own timing object",
     'blocked': 'frame-step stubs have no function-matched form yet'},
    {'what': 'screen shape and output size', 'now': 'build', 'goal': 'game', 'purpose': 'rendering',
     'why': "the display size, layout size and crop in nnMain and the display object, sead::PerspectiveProjection and nn::ui2d::Pane::Calculate",
     'blocked': 'frame-step stubs have no function-matched form yet'},
]
