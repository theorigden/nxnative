# The Legend of Zelda: Ocarina of Time (0400486024DEC000): the rewriter's patches of this game's own code. dm/tools/patch_nso.py loads every profile's patches.py;
# MATCH_FRAME_STEP as described there ("Registered patches"). Patches of Nintendo SDK module builds are in dm/tools/sdk_patches.py
from nso_asm import ADRP, B

# The game's frame ratio. Once a frame the function at main+0x6e6be0 (v131072) divides its base rate (60.0, or 30.0 while bit 0 of [x21+0x24f] is set) by the int frame rate at
# [x21+0x2c8] (fdiv s8,s1,s0 at +0xe4) and hands the result to the time object (main+0x3b4e300: ratio at +0x10, 1 / ratio at +0x14, round(60 / ratio) at +0x1c), which the game
# steps by; the frame's own time never enters it, so a frame that takes two vsyncs at rate 60 plays at half speed. The stub gives the ratio the host's step instead: step × base / 60
# (the division's value when the host keeps frames 60 / rate vsyncs), and counts the vsyncs stepped. Until the host has decided a step, and at fps_target 0, the division runs.
# s0 and x16 / x17 are free there (s0 is written again on every path before it is read; the function uses neither x16 nor x17); s1 keeps the base rate.
# Lichii (a GPL emulator; only the fact was taken) found the division (its notes: main+0x6E6CC4, 60 / [x21+0x2C8])
def frame_step(ctx):
    here, emit, fs_site, fs_put, FS_STATE_OFF, base = ctx.here, ctx.emit, ctx.site, ctx.put, ctx.state, ctx.base
    site = base + 0xe4
    fs_site(site, '2818201e')   # fdiv s8,s1,s0
    start = here(); emit(ADRP(16, here(), FS_STATE_OFF))
    for w in (0xb9400211,   # ldr w17,[x16]          target fps (0 = off)
              0x340001b1,   # cbz w17,orig (+13)
              0xb9402211,   # ldr w17,[x16,#0x20]    step in vsyncs
              0x34000171,   # cbz w17,orig (+11)     not decided yet
              0x1e230220,   # ucvtf s0,w17
              0xf9401a10,   # ldr x16,[x16,#0x30]
              0x8b110210):  # add x16,x16,x17
        emit(w)
    emit(ADRP(17, here(), FS_STATE_OFF))
    for w in (0xf9001a30,   # str x16,[x17,#0x30]    vsyncs stepped
              0x1e210808,   # fmul s8,s0,s1          step × base rate
              0x52a84e10,   # mov w16,#0x42700000    60.0
              0x1e270200,   # fmov s0,w16
              0x1e201908):  # fdiv s8,s8,s0          / 60
        emit(w)
    emit(B(here(), site + 4))
    emit(0x1e201828); emit(B(here(), site + 4))   # orig: fdiv s8,s1,s0; back
    fs_put(site, [B(site, start)], 'frame ratio: the host\'s step × base rate / 60 instead of base rate / the game\'s frame rate (state page target fps; 0 = the game\'s ratio)')
    dynamic_resolution(ctx)

# The game's dynamic resolution (game__gfx__DynamicResolutionParam: LoadThreshold, ReduceCounterMax, IncreaseCounterMax and a list of levels, each a ResolutionReduceScale and a
# Priority; on v131072 levels 0..9 at 0.75..0.333 of 2048x1152, 1536x864 to 683x384). Its update (main+0x805aa0) reads the frame's GPU load (about 0.2 ms a unit) into +0x8, subtracts
# its small model of the fixed costs and divides the rest by the square of the current scale: it takes the rest of the frame's cost to grow with the pixel count, as on the Switch 2
# its constants were tuned for. The level function (main+0x8065e0) adds that back times each level's scale squared and returns the best level under the threshold (+0x10, 83 = about
# 16.4 ms). On Apple GPUs this game's cost hardly depends on the resolution (mesh, compute and the upscaler's fixed 2048x1152 dominate): 683x384 cost 14.3 ms and 1536x864 14.7 ms on
# an M4 Pro, yet at 683x384 the extrapolation put 1536x864 at about 300 units against the 83 it allows, so the controller sat at its floor for good (game note, Dynamic resolution).
# The stub replaces the level function. With DM_DYNAMIC_RESOLUTION 0 (the default; state +0x40 0) it returns 0: full resolution. With 1 it climbs on what was measured at each
# level, with no model of how the cost grows: one level down when the load (+0x8) has been over the threshold for 8 calls in a row, and that level is marked as not fitting; one level
# up when the load fits and the level above was never measured, fitted when it was last measured, or was measured more than 600 calls (about 10 s) ago; else the current level
# (+0x174). Nothing is decided or recorded until a level has held 8 calls: the load is read a few frames late, so before that it may be the previous level's. The 8 calls over in a
# row keep a single slow frame, or the first frames at a new size (its render targets), from marking a level that fits (on the full library at level 1: one burst to 90 against loads
# of 77-80 at levels 2 and 1). The game's counters still pace the steps (down after ReduceCounterMax frames, up after IncreaseCounterMax); its level count (+0x1a0) is the floor.
# The memory is in the state page: +0x200 calls, +0x204 the last call's level, +0x208 calls at it, +0x20c calls over in a row, +0x210 the load measured at each level (16 floats),
# +0x250 the call it was measured at (0 = never). Run against a model of the update (a level moves after the stub asked 5 times up or 2 times down; the load two frames late): a load
# of 70 at every level climbs from the floor to full size in 9 steps, as does Ocarina's measured 72-80 with a spike every 37 frames and a burst after each change; a load that grows
# with the pixel count settles at the highest level that fits and tries the one above once per 600 calls; a scene that gets lighter climbs again, a heavier one steps down.
# The function is a leaf: x2..x11, x16, x17 and s0..s2 are free, w0 its only result (the original also stores its predicted cost at +0x18, which only it and the update's own
# decision read). The update's fingerprint is required too: +0x8 and +0x174 are its fields
drs_controller = (   # drs_stub.s, assembled with clang; x0 the controller, x16 the state page (the ADRP before it)
    0xb9404211, 0x35000071, 0x2a1f03e0, 0xd65f03c0,                                                   # off (state +0x40 0): level 0
    0xbd400800, 0xbd401001, 0xb9417402, 0xb941a003, 0x7100005f, 0x1a9fa042, 0x528001e9, 0x6b09005f,   # load, threshold, level (0..15), count
    0x1a89d042, 0xb9420204, 0x11000484, 0xb9020204, 0xb9420605, 0xb9420a06, 0x6b0200bf, 0x1a8617e6,   # calls + 1; calls at this level
    0xb9020602, 0xb9020a06, 0x35000046, 0xb9020e1f, 0x91084207, 0x91094208, 0x710020df, 0x5400040b,   # a new level: none over; under 8 calls: stay
    0x1e212000, 0x540001ad, 0xb9420e0b, 0x1100056b, 0xb9020e0b, 0x7100217f, 0x5400032b,               # over: under 8 in a row, stay
    0xbc2258e0, 0xb8225904, 0x51000469, 0x1100044a, 0x6b09015f, 0x1a89d140, 0xd65f03c0,               # 8 in a row: record it, down one (to the floor)
    0xb9020e1f, 0xbc2258e0, 0xb8225904, 0x34000182, 0x51000449, 0xb869590a, 0x340000ea, 0x4b0a008a,   # fits: record it; at 0 stay; the level above's record
    0x7109615f, 0x54000088, 0xbc6958e2, 0x1e212040, 0x540000aa, 0x2a0903e0, 0xd65f03c0,               # never, stale or fitting: up one
    0x2a1f03e0, 0xd65f03c0, 0x2a0203e0, 0xd65f03c0)                                                   # 0; or stay
def dynamic_resolution(ctx):
    here, emit, fs_site, fs_put, FS_STATE_OFF = ctx.here, ctx.emit, ctx.site, ctx.put, ctx.state
    site = ctx.others.get('dynamic resolution')
    if site is None or ctx.others.get('dynamic resolution update') is None: return   # not both found in this build (a red line from the locator): the game's own dynamic resolution
    fs_site(site, '017c40bd')   # ldr s1,[x0,#0x7c]
    start = here(); emit(ADRP(16, here(), FS_STATE_OFF))
    for w in drs_controller: emit(w)
    fs_put(site, [B(site, start)], 'dynamic resolution level: 0 (full resolution), or with state +0x40 (DM_DYNAMIC_RESOLUTION) a climb on the load measured at each level')
    ctx.capabilities.add('DYNAMIC_RESOLUTION')
    render_scale(ctx)

# Render scale (state +0x10, a float the loader writes: DM_RENDER_SCALE, 0.5 to 1.0). The dynamic-resolution update (main+0x805aa0 on v131072) turns its current level into the
# fraction its caller (main+0x31d3ee0) sizes the 3D views by: it finds the level in its list (head at +0x198, the list's end at +0x190; a node's index at -4, its
# ResolutionReduceScale at -8), multiplies the scale by the base width (+0x7c), floors that to the alignment (+0x80) and divides by the width at +0x90. Level 0, 0.75, is the
# game's top internal size, 1920x1080 of the 2560x1440 output docked. That happens at two sites, +0x480 and +0x890 into the update, each `ldur s1, [x9, #-8]`, and every level the
# update returns goes through one of them (the others return 1.0, the update's own off state). The stub takes the smaller of the level's scale and level 0's scale × the render
# scale: with Dynamic resolution off (the level stub holds level 0) a fixed share of the top size; with it on, the levels above that share are held to it and those below it
# keep their own, so the climb works under the cap. A render scale of 0 (not set) or 1.0 leaves the original. x11, x16, x17, s0 and s2 are free at both sites: s0, s2 and the
# flags are written again within 5 instructions, and x11 is not read again before the update returns
rs_cap = (   # rs_stub.s, assembled with clang; x16 the state page (the ADRP before it)
    0xbc5f8121, 0xbd401200, 0x1e202008, 0x5400020d,   # ldur s1, [x9, #-8] (original); ldr s0, [x16, #0x10]; fcmp s0, #0.0; b.le done
    0x1e2e1002, 0x1e222000, 0x540001aa,               # fmov s2, #1.0; fcmp s0, s2; b.ge done
    0xf940ce71, 0x91064270,                           # ldr x17, [x19, #0x198]; add x16, x19, #0x190
    0xeb10023f, 0x54000120, 0xb85fc22b, 0x3400006b,   # loop: cmp x17, x16; b.eq done; ldur w11, [x17, #-4]; cbz w11, found
    0xf9400631, 0x17fffffb,                           # ldr x17, [x17, #8]; b loop
    0xbc5f8222, 0x1e200842, 0x1e222020, 0x1e21cc41)   # found: ldur s2, [x17, #-8]; fmul s2, s2, s0; fcmp s1, s2; fcsel s1, s2, s1, gt
def render_scale(ctx):
    here, emit, fs_site, fs_put, FS_STATE_OFF = ctx.here, ctx.emit, ctx.site, ctx.put, ctx.state
    update = ctx.others['dynamic resolution update']
    for site in (update + 0x480, update + 0x890):
        fs_site(site, '21815fbc')   # ldur s1, [x9, #-8]
        start = here(); emit(ADRP(16, here(), FS_STATE_OFF))
        for w in rs_cap: emit(w)
        emit(B(here(), site + 4))
        fs_put(site, [B(site, start)], 'dynamic resolution scale: at most level 0\'s × the host render scale (state +0x10; 0 or 1.0 = the game\'s)')
    ctx.render_scale = 1

# Screen shape and output size (profile keys screen_aspect and output_size; the loader's state page +0x48 output height, +0x50 layout height (float), +0x68 output width,
# loader.c dm_fps_state_apply: DM_SCREEN_ASPECT, DM_OUTPUT_RES). The game's sizes are Tears of the Kingdom's at 4/3: docked it renders a 2560x1440 output (its top internal
# 3D size 1920x1080, Dynamic resolution's level 0) with a 1280x720 layout space. The loader's sizes are 1920 wide unless DM_OUTPUT_RES gives a width (+0x68), so an
# output width of 0 here means the game's own 2560 and the loader's height x 4/3 (1920x1200 at 16:10 → 2560x1600). The sites, as in Tears of the Kingdom's screen_shape
# (0100F2C0115B6000/patches.py), on v131072:
# - nnMain passes the framework its display size, x8 = 2560 | 1440 << 32 (main+0x1202ee0 / +0x1202ee4, stored at [x21, #0x14]), which it takes for the frame buffer and the window
#   textures; and the layout (virtual) size 1280.0 x 720.0 (main+0x1203084 / +0x12030a0, to main+0x346be50), whose height becomes the loader's layout height.
# - The display object's crop request (main+0xe9a860, the same function as Tears of the Kingdom's main+0x3de5b0: +0xac x, y, +0xb4 w, h), which nvnWindowSetCrop takes for the
#   presented picture: a 2560x1440 crop becomes the output's size.
# - The final image: main+0x652260 sizes each agl::RenderDisplay (+0x770 / +0x774 floats) as the display-mode object's slot i (+0x10 + i*0xc, int w, h) x its scale (s0 / s1),
#   the same loop as Tears of the Kingdom's main+0x8d760 (+0x7a8): a 2560x1440 slot becomes the output's size. x16 / x17 are free there (x11 is written after the site).
# x16 and x17 are free at every site (nnMain: x16 is not read between the sites and the calls after them; the crop setter is a leaf)
def _out_size(emit):
    """w16 = the output width, w17 its height, from the state page in x16 and w17 = its +0x48 (not 0): +0x68 when set, else the game's 2560 and the height x 4/3"""
    for w in (0xb9406a10,   # ldr w16, [x16, #0x68]   output width (0 = the game's)
              0x350000b0,   # cbnz w16, have (+5)
              0x531e7631,   # lsl w17, w17, #2
              0x52800070,   # mov w16, #3
              0x1ad00a31,   # udiv w17, w17, w16      height x 4/3
              0x52814010):  # mov w16, #2560
        emit(w)
def screen_shape(ctx):
    here, emit, fs_site, fs_put, STATE = ctx.here, ctx.emit, ctx.site, ctx.put, ctx.state
    def stub(site, orig, words, why):   # words: ints, None for the state page's adrp into x16, 'size' for _out_size
        fs_site(site, orig)
        start = here()
        for w in words:
            if w is None: emit(ADRP(16, here(), STATE))
            elif w == 'size': _out_size(emit)
            else: emit(w)
        emit(B(here(), site + 4))
        fs_put(site, [B(site, start)], why)
    stub(0x1202ee4, '08b4c0f2', (0xf2c0b408,   # movk x8, #0x5a0, lsl #32 (original): 2560 | 1440 << 32
                                 None, 0xb9404a11, 0x34000111,   # ldr w17, [x16, #0x48]; cbz w17, done (+8)   no screen shape or output size
                                 'size', 0xaa118208),   # have: orr x8, x16, x17, lsl #32
         'display size 2560x1440 (frame buffer, window textures) → the host\'s output size')
    stub(0x12030a0, '8886e8f2', (0xf2e88688,   # movk x8, #0x4434, lsl #48 (original): 1280.0 | 720.0 << 32
                                 None, 0xb9405210, 0x34000050, 0xb3607e08),   # ldr w16, [x16, #0x50]; cbz w16, done; bfi x8, x16, #32, #32
         'layout size 1280x720 → the host\'s layout height')
    stub(0xe9a868, '03901629', (None, 0xb9404a11, 0x340001b1,   # ldr w17, [x16, #0x48]; cbz w17, orig (+13)
                                0x7128007f, 0x54000161, 0x7116809f, 0x54000121,   # cmp w3, #2560; b.ne orig; cmp w4, #1440; b.ne orig
                                'size', 0x2a1003e3, 0x2a1103e4,   # have: mov w3, w16; mov w4, w17
                                0x29169003),   # orig: stp w3, w4, [x0, #0xb4]
         'window crop 2560x1440 → the host\'s output size')
    stub(0x65238c, '420d422d', (0x2d420d42,   # ldp s2, s3, [x10, #0x10] (original): the slot's int width and height
                                0xf9400951, 0xd2814010, 0xf2c0b410, 0xeb10023f, 0x54000181,   # ldr x17, [x10, #0x10]; mov x16, #2560 | 1440 << 32; cmp; b.ne done (+12)
                                None, 0xb9404a11, 0x34000131,   # ldr w17, [x16, #0x48]; cbz w17, done (+9)
                                'size', 0x1e270202, 0x1e270223),   # have: fmov s2, w16; fmov s3, w17 (ints: the scvtf after the site converts them)
         'final image (agl::RenderDisplay) 2560x1440 → the host\'s output size')

# Build v131072 (e0f3ccfa…): the frame step at its matched functions, then the screen-shape stubs, whose sites are this build's fixed addresses
def frame_step_131072(ctx):
    ctx.base, ctx.others = 0x6e6be0, {'dynamic resolution': 0x8065e0, 'dynamic resolution update': 0x805aa0}
    frame_step(ctx)
    screen_shape(ctx)

FRAME_STEP = {'e0f3ccfaf50065ae4ea01eb5aeb13b1a': frame_step_131072}

MATCH_FRAME_STEP = {'main': [
    {'name': 'frame ratio from the host\'s step', 'size': 0x9b4, 'fingerprints': ['6ae2aff5344d14568e4dbaf93455e2d8278384bf892ed6c6eca87fef98fbcd1d'], 'stub': frame_step,   # v131072 main+0x6e6be0
     'others': {'dynamic resolution': {'size': 0x294, 'fingerprints': ['7af6ceb0aedf8e0c17dc08ce17fcd6a7cba6d394a0d09e3b504c6d668dc418e7']},   # v131072 main+0x8065e0
                'dynamic resolution update': {'size': 0xb24, 'fingerprints': ['5a423697838976baf286cffa5e2ceef0d4e037abbcd9d371e90e9e702d61b3d4']}}},   # main+0x805aa0
]}

# The movie player's pictures per frame. Once a frame the player's update (main+0x3b5ca60 on v131072) adds the frame's time (the time object's +0x18, the frame ratio / 60 s, times
# 60) to a count at +0x8, takes its whole pictures (the movie's rate at the player's +0x324; the title's and the opening's are 60 fps) and advances that many (main+0x3b61ea0 pops them from its
# queue and shows the last), but never more than the player's +0x20 (csel at main+0x3b5cb2c), and the count keeps what was left. The constructor (main+0x3b5cec0) sets +0x20 to
# 1, or to 2 when its last argument is 2 or more (cmp w27, #2; cinc w8, w28, ge at +0x1c4, w28 = 1), and the queue's size at +0x50 to twice that; the game's one caller passes 1
# (main+0x3b5c55c). So a frame of two vsyncs shows one picture where the movie had two, the picture falls behind for good (the count only grows), and the movie's sound, a stream of
# the sound engine on real time, runs ahead and ends before the picture: at a 30 fps frame step a movie played at exactly 0.500 of its speed (58.00 s of movie in 115.95 s) with
# the count at 1,350 pictures after 45 s. The console holds one vsync a frame in its movies, so the limit never shows there; here the frame step hands the game steps of 2 and 3.
# The cut gives the constructor's own value for 2 (+0x20 = 2, +0x50 = 4), so a frame of two vsyncs shows every second picture and a movie that fell behind catches up at two
# pictures a frame: at the 30 fps frame step 1.000 (95.00 s in 94.97 s).
movie_pictures = 'movie pictures a frame: up to 2, the constructor\'s value for an argument of 2 or more, whatever its caller passes (1)'
# The update's cap, 3. The constructor's limit also sizes the decoder's pipeline: the picture pool is twice it (video-frame-count, registered from a four-slot array at the player's
# +0x168, which the teardown frees slot by slot) and the inputs in flight are as many as it (their buffers two slots at +0x188 and +0x190: main+0x3b5ff30 takes slot 0 for an id of
# 2 or more). So 3 cannot be the limit: with the game's pool of 6 the registration wrote over the two input buffers (the game stopped at the movie's start with a copy to a null
# pointer in sdk), and with the pool kept at 4 the third input reused slot 0 while in flight (a VideoToolbox decode error after 150 pictures of the title movie). The frame step's
# largest hold is 3 vsyncs, and with a cap of 2 each such frame left the picture one behind for as long as the step stayed at 2. The update reads the limit only for its cap
# (ldr w9, [x0, #0x20] at +0xc0, before the csel); the cut puts 3 there and leaves the limit, the pool and the inputs at the constructor's 2. The advance pops up to that many from
# its own queue and stops when the queue is empty, so a frame takes a third picture only when the decoder has one.
movie_cap = 'movie update cap: 3 pictures a frame, the frame step\'s largest hold, in place of the limit (2), which also sizes the decoder pipeline'
# The movie's frame, which its event follows. The event that plays a movie (its update main+0x3b3e9a0 on v131072) reads the movie's frame (its vtable's +0x78, main+0x3b3ec10: the
# movie object's int at +0x2f8) and moves its timeline up to it when the timeline is behind (main+0x122d520), then measures the movie's sound stream against it (main+0x3b3ea50).
# The opening's timeline carries its subtitles, the narrator's voice lines (EventFlowMsg/Dm_Kokiri_0000, played with them), its rumble and the title logo
# (EventOpenOpeningTitle). The movie's draw (main+0x3b5c710, and main+0x3b5c870 for its first draw) adds 1 to that frame each frame a picture is on screen (ldr, add #1,
# str at +0xb4 and +0x98), so the frame counts frames drawn, not pictures shown: the same while the player takes one picture a frame, half of them when it takes two. With the
# cut above, a frame of two vsyncs showed the picture in real time but the subtitles and voice at half speed, and the logo, due after the movie's end, never showed. The cut
# sets the frame to the pictures the player has taken (the player's +0xc: its update adds what it advances each frame; reset when a movie starts, as +0x2f8 is), so the
# timeline follows the picture whatever the frame takes. The player is the object at +0x10, already read by both draws (main+0x3b5ce80 on it) just before.
movie_frame = 'movie frame: the pictures the player has taken (its +0xc), not 1 more for each frame drawn'
MATCH_CUTS = {'main': [
    {'name': movie_pictures, 'size': 828, 'fingerprints': ['f61ad468b6b4e1d574fe8678f5a12dfc60e1aab71be7375142a4b48b0d73ce19'],   # v131072 main+0x3b5cec0
     'cuts': [(452, '88b79c1a', '48008052', movie_pictures + ' (cinc w8, w28, ge → mov w8, #2; as v131072 main+0x3b5d084)')]},
    {'name': movie_cap, 'size': 368, 'fingerprints': ['6a29b27559214b3b89cc31a5b85f14bda4a55685f1ae4fe486d53eda66855867'],   # v131072 main+0x3b5ca60, the update
     'cuts': [(192, '092040b9', '69008052', movie_cap + ' (ldr w9, [x0, #0x20] → mov w9, #3; as v131072 main+0x3b5cb20)')]},
    {'name': movie_frame, 'functions': [
        {'size': 344, 'fingerprints': ['cc1ca04feb1ca4e553a6c7a4f36f99b13f56977185eea8ef5cd8dd3dbbdcdbcd'],   # v131072 main+0x3b5c710, the draw
         'cuts': [(180, '88fa42b908050011', '880a40f9080d40b9', movie_frame + ' (ldr w8, [x20, #0x2f8]; add w8, w8, #1 → ldr x8, [x20, #0x10]; ldr w8, [x8, #0xc]; as v131072 main+0x3b5c7c4)')]},
        {'size': 196, 'fingerprints': ['8fe123ca6fcd016cd9c718e5e66035c807b27f63408861235765e47b4ec34da3'],   # v131072 main+0x3b5c870, the first draw
         'cuts': [(152, '88fa42b908050011', '880a40f9080d40b9', movie_frame + ' (the same; as v131072 main+0x3b5c908)')]},
    ]},
]}

BINDING = [
    {'what': 'movie pictures a frame: up to 2', 'now': 'game', 'goal': 'game', 'purpose': 'frame rate',
     'why': "the game's own movie player constructor, found by its function's fingerprint on any build that keeps the function; no other game has it: the fingerprint matches no function in the mains of Donkey Kong Bananza, Splatoon Raiders, Pokopia, Mario Tennis Fever, Switch Sports, Yoshi and the Mysterious Book, Mario Golf, Xenoblade Chronicles 2 or Super Mario 3D All-Stars, and Breath of the Wild's and Tears of the Kingdom's movies go through subsdk0's movie::Decoder, not a player in main",
     'checked': 'v131072 main: one function with this fingerprint, the constructor, its one caller, the update and the advance read by disassembly; the limit and the count read in play with DM_PROBE, the opening movie timed at a 30 fps frame step without and with the cut (2026-11-12)'},
    {'what': 'movie update cap: 3 pictures a frame', 'now': 'game', 'goal': 'game', 'purpose': 'frame rate',
     'why': "the game's own movie player update, found by its function's fingerprint on any build that keeps the function; it goes with the player's two-picture cut and has no wider binding",
     'checked': 'v131072 main: one function with this fingerprint, the cap\'s only read of the limit, the pool and input slots the limit sizes and the advance read by disassembly; the opening with frames forced to three vsyncs at cap 2, limit 3 with pool 4 (decode error) and cap 3 (2026-11-16)'},
    {'what': 'movie frame: the pictures the player has taken', 'now': 'game', 'goal': 'game', 'purpose': 'frame rate',
     'why': "the game's own movie draw functions, found by their functions' fingerprints on any build that keeps them; it is the counter the same game's player keeps, so it goes with the player's two-picture cut and has no wider binding",
     'checked': 'v131072 main: one function with each fingerprint, each with one caller, the event update that reads the frame (vtable +0x78), the timeline and sound syncs and the player\'s +0xc read by disassembly; the opening timed with frames forced to two vsyncs (2026-11-16)'},
    {'what': 'frame ratio from the host\'s step', 'now': 'game', 'goal': 'game', 'purpose': 'frame rate',
     'why': "the game's own frame-ratio division, found by its function's fingerprint on any build that keeps the function",
     'checked': 'v131072 main: one function with this fingerprint, the site and its free registers read by disassembly (2026-11-08)'},
    {'what': 'render scale: the dynamic resolution\'s scale at most level 0\'s × DM_RENDER_SCALE', 'now': 'game', 'goal': 'game', 'purpose': 'rendering',
     'why': "the game's own dynamic-resolution update, found by its function's fingerprint with the level function; the two sites read the update's level list",
     'checked': 'v131072 main: the update\'s two scale sites, its level list and its caller (main+0x31d3ee0, which sizes the 3D views from the returned scale) read by disassembly (2026-11-17); not yet run in the game'},
    {'what': 'screen shape and output size: display size, layout height, crop and final image', 'now': 'build', 'goal': 'game', 'purpose': 'rendering',
     'why': "fixed addresses of v131072, found by their constants (2560x1440, 1280.0 x 720.0) and by Tears of the Kingdom's crop setter and final-image loop, which are the same code here; no function-matched form yet",
     'checked': 'v131072 main: the four sites and their free registers read by disassembly against Tears of the Kingdom 1.4.3\'s (2026-11-17); not yet run in the game'},
    {'what': 'dynamic resolution: full size, or a climb on the load measured at each level', 'now': 'game', 'goal': 'game', 'purpose': 'rendering',
     'why': "the game's own dynamic-resolution level function and update, found by their functions' fingerprints on any build that keeps both; switchable (DM_DYNAMIC_RESOLUTION)",
     'checked': 'v131072 main: one function with each fingerprint (the level function a leaf, x2..x11 / x16 / x17 / s0..s2 free), its callers, the update and the controller fields read by disassembly, the fields read in play (2026-11-08); the climb run natively against a model of the update and in play to full size (2026-11-09)'},
]
