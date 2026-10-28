/* Reuse the proven disabled REC installer; add immutable label resources
 * before the first REC transition. Never install these prologues in REC:
 * normal rendering can call the font accessors asynchronously.
 */
#define bootstrap_main rec_bootstrap_main
#define HOOK_IMAGE 0x06b95c00
#include "rec_install_probe.c"
#undef bootstrap_main
#define BYTE(a) (*(volatile u8 *)(a))

__attribute__((section(".text.bootstrap")))
void bootstrap_main(void) {
    volatile struct report *s=(void *)0x06b95180;
    volatile u32 *r=(void *)0x06b951c0;
    r[0]=0x4c414231; r[1]=1;
    /* Fail before allocating or publishing any hook if the new target differs. */
    if (BYTE(0x01b7b518)!=12 || BYTE(0x01b6a020)!=7 ||
        WORD(0x0011c0f8)!=0x03e16c06 ||
        WORD(0x03eb6cbc)!=0xe52db004 || WORD(0x03eb6cc0)!=0xe28db000 ||
        WORD(0x03eb6d28)!=0xe52db004 || WORD(0x03eb6d2c)!=0xe28db000 ||
        WORD(0x06b953b8)!=0x4c414231 || WORD(0x06b953c4)!=0x206) {
        s->status=0x80000020; r[1]=0x80000020; return;
    }
    rec_bootstrap_main();
    if (s->status!=2) { r[1]=0x80000021; return; }
    s->status=1;
    if (s->allocation!=0x01c1cf10 || s->code!=0x01c1d000 ||
        s->data!=0x01c1e000 || s->code_size>0x400 ||
        WORD(0x01c1e014)!=0 || WORD(0x01c1e018)!=0 ||
        BYTE(0x01b7b518)!=12 || BYTE(0x01b6a020)!=7) {
        s->status=0x80000022; r[1]=0x80000022; return;
    }
    r[2]=(u32)PROTECT(0x01c1d000,0x1000,7);
    if (r[2]) { s->status=0x80000023; r[1]=0x80000023; return; }
    for (u32 i=0;i<0x200;i+=4) WORD(0x01c1d400+i)=0;
    for (u32 i=0;i<0x140;i+=4) WORD(0x01c1d400+i)=WORD(0x06b95040+i);
    for (u32 i=0;i<0x40;i+=4) WORD(0x01c1d5c0+i)=WORD(0x06b95390+i);
    __asm__ volatile("dsb sy" ::: "memory");
    r[3]=(u32)PROTECT(0x01c1d000,0x1000,5);
    if (r[3] || WORD(0x000a0474)!=0x01c1d7b6) {
        s->status=0x80000024; r[1]=0x80000024; return;
    }
    /* The cold Jig gate keeps publication ahead of normal rendering startup. */
    if (BYTE(0x01b7b518)!=12 || BYTE(0x01b6a020)!=7) {
        s->status=0x80000025; r[1]=0x80000025; return;
    }
    WORD(0x03eb6cc0)=0x01c1d400;
    WORD(0x03eb6cbc)=0xe51ff004;
    WORD(0x03eb6d2c)=0x01c1d440;
    WORD(0x03eb6d28)=0xe51ff004;
    __asm__ volatile("dsb sy" ::: "memory");
    r[4]=4;
    /* Force native cache/IPI synchronization, preserving the original RWX map. */
    r[5]=(u32)PROTECT(0x03e00000,0x100000,5);
    r[6]=(u32)PROTECT(0x03e00000,0x100000,7);
    r[7]=WORD(0x0011c0f8);
    if (r[5] || r[6] || r[7]!=0x03e16c06) {
        s->status=0x80000026; r[1]=0x80000026; return;
    }
    r[1]=2; s->status=2;
}
