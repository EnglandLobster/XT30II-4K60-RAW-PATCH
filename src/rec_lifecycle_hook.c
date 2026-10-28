/* A temporary UI-thread continuation, not a replacement capture pipeline.
 * Original Jig handling stays intact except for one explicitly armed MODE REC
 * request and its missing REC continuation after completed vendor deinit.
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

struct state {
    u32 magic, version, allocation, code_page, data_page;
    volatile u32 enabled, phase, calls, last_event, request_result;
    u32 original_hook, original_ui_mode, original_backend_mode;
    volatile u32 error, last_return, active;
    volatile u32 usb_checks, usb_ui, usb_boot, usb_debug;
    volatile u32 boot_before_rec, boot_after_rec, debug_before_rec, debug_after_rec;
};
extern struct state *hook_state(void);
#define WORD(a) (*(volatile u32 *)(a))
#define HALF(a) (*(volatile u16 *)(a))
#define BYTE(a) (*(volatile u8 *)(a))
#define CALL0(a) (((u32 (*)(void))(a))())
#define CALL1(a, x) (((u32 (*)(u32))(a))(x))

__attribute__((section(".text.hook")))
u32 rec_lifecycle_hook(void) {
    struct state *s = hook_state();
    if (s->magic != 0x52454348 || s->version != 2)
        return CALL0(0x01e670d0);
    s->active = 1;
    s->calls++;
    s->last_event = WORD(0x01b723e8);
    if (s->enabled == 1 && s->phase == 0 && s->last_event == 0x3001
            && BYTE(0x01b7b518) == 12 && BYTE(0x01b6a020) == 7) {
        if (CALL0(0x02014650) == 0) {
            s->error = 1;
            s->active = 0;
            return 0;
        }
        s->phase = 1;
        s->request_result = CALL1(0x02009a70, 1);
        if (s->request_result != 3) {
            s->error = 2;
            s->phase = 0x80000001;
            s->enabled = 0;
        }
        CALL1(0x0200ef18, 1); /* Preserve stock consumed-event bookkeeping. */
        s->active = 0;
        return 1;
    }
    u32 result = CALL0(0x01e670d0);
    s->last_return = result;
    if (s->enabled == 1 && s->phase == 1 && result == 0x38
            && BYTE(0x01b7b518) == 3) {
        s->phase = 2;
        s->boot_before_rec = BYTE(0x01b6a020);
        s->debug_before_rec = CALL1(0x01272d54, 0xf7);
        /* Match the original normal-mode wrapper's target-REC branch. */
        HALF(0x02cddeb4) = 3;
        CALL0(0x01f99320);
        CALL1(0x01f99424, 0x1c);
        CALL0(0x02018438);
        BYTE(0x01b813c6) = 0;
        CALL1(0x01fa37f0, 0);
        CALL0(0x01e4bd10);
        s->boot_after_rec = BYTE(0x01b6a020);
        s->debug_after_rec = CALL1(0x01272d54, 0xf7);
        s->phase = 3; /* Submitted; does not claim sensor/USB readiness. */
        s->enabled = 0; /* This transition is strictly single-shot. */
    } else if (s->enabled == 1 && s->phase == 1 && result == 0x38) {
        s->error = 3;
        s->phase = 0x80000002;
        s->enabled = 0;
    }
    s->active = 0;
    return result;
}

/* Called only from stock attach's boot-mode==7 branch. Other boot modes,
 * f7==0, connection-edge checks and all stock USB work remain unchanged. */
u32 usb_attach_allowed(void) {
    struct state *s = hook_state();
    if (s->magic != 0x52454348 || s->version != 2) return 0;
    s->usb_checks++;
    s->usb_ui = BYTE(0x01b7b518);
    s->usb_boot = BYTE(0x01b6a020);
    s->usb_debug = CALL1(0x01272d54, 0xf7);
    return s->phase == 3 && s->usb_ui >= 3 && s->usb_ui <= 7
        && s->usb_boot == 7 && s->usb_debug != 0;
}
