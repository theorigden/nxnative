// Face buttons of the shared GameController adapter (pad_apple.h) with fake pads: by position on most pads, by label on a Nintendo pad, and by label on every pad
// with DM_PAD_FACE=label; no physical controller is needed.
#import "../pad_apple.h"
#include <assert.h>
#include <stdio.h>

@interface TestButton : NSObject
@property BOOL isPressed;
@end
@implementation TestButton
@end
@interface TestController : NSObject
@property NSString *productCategory;
@end
@implementation TestController
@end
@interface TestPad : NSObject
@property TestController *controller;
@property TestButton *buttonA, *buttonB, *buttonX, *buttonY;
@end
@implementation TestPad
@end

// The Switch buttons of a pad of this category with only the named GameController button pressed; by_label: DM_PAD_FACE=label's mapping
static uint64_t face_mapped(NSString *category, char pressed, int by_label) {
    TestPad *g = [TestPad new]; g.controller = [TestController new]; g.controller.productCategory = category;
    g.buttonA = [TestButton new]; g.buttonB = [TestButton new]; g.buttonX = [TestButton new]; g.buttonY = [TestButton new];
    TestButton *b = pressed == 'A' ? g.buttonA : pressed == 'B' ? g.buttonB : pressed == 'X' ? g.buttonX : g.buttonY;
    b.isPressed = YES;
    return dm_pad_face_mapped((GCExtendedGamepad *)(id)g, by_label);
}
static uint64_t face(NSString *category, char pressed) { return face_mapped(category, pressed, 0); }

int main(void) { @autoreleasepool {
    for (NSString *k in @[@"Xbox One", @"DualSense", @"HID"]) {   // by position: buttonA bottom (B), buttonB right (A), buttonX left (Y), buttonY top (X)
        assert(face(k, 'A') == DM_BTN_B); assert(face(k, 'B') == DM_BTN_A); assert(face(k, 'X') == DM_BTN_Y); assert(face(k, 'Y') == DM_BTN_X);
    }
    assert(face(nil, 'B') == DM_BTN_A);   // no category: by position
    for (NSString *k in @[@"Switch Pro Controller", @"Nintendo Switch Joy-Con (L/R)", @"Nintendo Switch Joy-Con (R)"]) {   // by label
        assert(face(k, 'A') == DM_BTN_A); assert(face(k, 'B') == DM_BTN_B); assert(face(k, 'X') == DM_BTN_X); assert(face(k, 'Y') == DM_BTN_Y);
    }
    // DM_PAD_FACE=label: every pad by its letters (an Xbox pad's bottom A is the Switch's A, a PlayStation pad's cross too), a Nintendo pad as before
    for (NSString *k in @[@"Xbox One", @"DualSense", @"HID", @"Switch Pro Controller", @"Nintendo Switch Joy-Con (R)"]) {
        assert(face_mapped(k, 'A', 1) == DM_BTN_A); assert(face_mapped(k, 'B', 1) == DM_BTN_B); assert(face_mapped(k, 'X', 1) == DM_BTN_X); assert(face_mapped(k, 'Y', 1) == DM_BTN_Y);
    }
    // dm_pad_face follows DM_PAD_FACE, read at its first call: label here
    setenv("DM_PAD_FACE", "label", 1);
    TestPad *p = [TestPad new]; p.controller = [TestController new]; p.controller.productCategory = @"Xbox One";
    p.buttonA = [TestButton new]; p.buttonA.isPressed = YES;
    assert(dm_pad_face((GCExtendedGamepad *)(id)p) == DM_BTN_A);
    TestPad *g = [TestPad new];   // nothing pressed, buttons nil: none
    assert(dm_pad_face((GCExtendedGamepad *)(id)g) == 0);
    printf("t_pad_apple OK\n");
} return 0; }
