// Settings a running game takes at once (settings_live.c), for the in-game menus: the Mac's settings panel (front_mac.m, settings_menu_mac.h) and the iPhone's menu
// (front_ios.m dm_setting_live, GameMenu.swift). Each is a launcher setting (dm/games/settings.tsv) whose value the host reads while the game runs: the host tone map's
// grade (nvn_hdr.inc mtl_grade_set, read by every tone map pass), the frame step state page's frame-rate target and render scale (loader.c; the frame step reads the target
// at every present, the rewriter's stubs read the scale each time the game sizes its views) and rumble. Settings of the front end itself (HDR, the Metal HUD, the iPhone's
// picture fit) are the front end's, before it asks here. The other settings are read once, when the game starts: an in-game menu saves them for the next start.
#pragma once

// value NULL: whether env can change while this game runs (1) or needs the next start (0). Otherwise: apply value now (and put it in the environment, as the launcher does);
// 1 when it took effect, 0 when env is not live or the value is not one it takes (nothing changes then)
int settings_live_apply(const char *env, const char *value);
