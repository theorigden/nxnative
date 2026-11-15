// A physical controller's face buttons as Switch buttons, shared by the Mac front end (front_mac.m) and the iOS gamepad (DmGamepad.m). GameController names most pads' face
// buttons by position, as on an Xbox pad (buttonA bottom, buttonB right, buttonX left, buttonY top), but a Nintendo pad's by their printed labels (buttonA is the right
// button, marked A): a Switch Pro Controller (or a pad that presents itself as one) and Joy-Con (productCategory "Nintendo Switch Joy-Con (L)", "(R)", "(L/R)").
// The Switch's layout is right A, bottom B, top X, left Y, so a Nintendo pad maps name for name and any other pad by position. Checked with a Pro Controller on the Mac
// and on iOS (PR #650). Open: a single Joy-Con held sideways is matched too and has not been tried; if GameController keeps its labels there instead of turning them
// with the controller, its face buttons come out a quarter turn off.
// The player can map the other pads by their printed letters instead (DM_PAD_FACE=label, the settings' Controller buttons): an Xbox pad's A, the bottom button, is then
// the Switch's A and its B the Switch's B, as most Xbox and PC games use them, while the Switch's own layout puts B at the bottom. A PlayStation pad's cross is then A. A
// Nintendo pad maps by its labels either way; raw HID pads (pad_hid_mac.h) have DM_HID_MAP instead.
#pragma once
#import <GameController/GameController.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "dm_input.h"

static inline int dm_pad_labelled(GCController *c) {
    NSString *k = c.productCategory;
    return [k isEqualToString:@"Switch Pro Controller"] || [k containsString:@"Joy-Con"];
}
// DM_PAD_FACE: label = every pad by its labels; position (the default, or anything else) = by position but a Nintendo pad. Read once, when the first button is read
static inline int dm_pad_by_label_env(void) {
    static int v = -1;
    if (v < 0) { const char *e = getenv("DM_PAD_FACE"); v = e && !strcmp(e, "label"); }
    return v;
}
// DM_BTN_A / B / X / Y of the pad's pressed face buttons; by_label: map a pad that names its buttons by position by its letters (buttonA is then A)
static inline uint64_t dm_pad_face_mapped(GCExtendedGamepad *g, int by_label) {
    GCControllerButtonInput *a = g.buttonA, *b = g.buttonB, *x = g.buttonX, *y = g.buttonY;
    if (!by_label && !dm_pad_labelled(g.controller)) { GCControllerButtonInput *t = a; a = b; b = t; t = x; x = y; y = t; }   // by position: right A, bottom B, top X, left Y
    return (a.isPressed ? DM_BTN_A : 0) | (b.isPressed ? DM_BTN_B : 0) | (x.isPressed ? DM_BTN_X : 0) | (y.isPressed ? DM_BTN_Y : 0);
}
static inline uint64_t dm_pad_face(GCExtendedGamepad *g) { return dm_pad_face_mapped(g, dm_pad_by_label_env()); }
