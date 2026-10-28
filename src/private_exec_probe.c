/* One-shot proof of executable PRIVATE heap ownership. Runs from the already
 * validated inactive log page. Does not install hooks or change any mode.
 * A failed protection restore intentionally retains ownership until reboot.
 */
typedef unsigned int u32;
#define WORD(a) (*(volatile u32 *)(a))
#define CALL1(a, x) (((u32 (*)(u32))(a))(x))
#define PROTECT(a, n, p) (((int (*)(u32,u32,u32))0x0128bc9c)(a,n,p))

struct report {
    u32 magic, status, allocation, page, l1_before, l1_after;
    u32 protect_result, call_result, restore_result, freed;
};

__attribute__((section(".text.probe")))
void private_exec_probe(void) {
    volatile struct report *s = (void *)0x06b95180;
    s->magic = 0x50525831;
    s->status = 1;
    u32 raw = CALL1(0x013d77a4, 0x2000);
    s->allocation = raw;
    if (!raw) { s->status = 0x80000001; return; }
    u32 page = (raw + 0xfff) & ~0xfffU;
    s->page = page;
    /* Native malloc was fingerprinted in this module's data allocation.
     * Do not change permissions if its ownership/mapping is unexpected. */
    if (raw < 0x0172e000 || raw > 0x01e10000 ||
        page + 0x1000 > raw + 0x2000) {
        s->status = 0x80000002;
        CALL1(0x013d77c4, raw);
        s->freed = 1;
        return;
    }
    u32 l1 = WORD(0x0011c000 + (page >> 20)*4);
    s->l1_before = l1;
    /* Only the currently observed identity RW/XN normal-memory section.
     * This experiment may split it into a stock-allocated coarse table. */
    if (l1 != ((page & 0xfff00000) | 0x16c16)) {
        s->status = 0x80000003;
        CALL1(0x013d77c4, raw);
        s->freed = 1;
        return;
    }
    /* ARM: movw r0,#0x51a7; bx lr. No data or system side effects. */
    WORD(page) = 0xe30501a7;
    WORD(page+4) = 0xe12fff1e;
    int result = PROTECT(page, 0x1000, 5); /* R/X, never W/X. */
    s->protect_result = (u32)result;
    if (result) { s->status = 0x80000004; return; }
    s->call_result = ((u32 (*)(void))page)();
    s->restore_result = (u32)PROTECT(page, 0x1000, 3);
    s->l1_after = WORD(0x0011c000 + (page >> 20)*4);
    if (s->restore_result) { s->status = 0x80000005; return; }
    CALL1(0x013d77c4, raw);
    s->freed = 1;
    s->status = s->call_result == 0x51a7 ? 2 : 0x80000006;
}
