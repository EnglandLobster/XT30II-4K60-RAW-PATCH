/* Install only a DISABLED lifecycle observer. Its allocation stays owned until
 * a cold restart; never free code reachable from an asynchronously called hook.
 * No mode request, key event, FPS or persistent configuration change here.
 */
typedef unsigned int u32;
typedef unsigned char u8;
#define WORD(a) (*(volatile u32 *)(a))
#define CALL1(a,x) (((u32 (*)(u32))(a))(x))
#define PROTECT(a,n,p) (((int (*)(u32,u32,u32))0x0128bc9c)(a,n,p))
#define SLOT 0x02581e78
#define ORIGINAL 0x01e670d0
#ifndef HOOK_IMAGE
#define HOOK_IMAGE 0x06b95a00
#endif

struct report {
    u32 magic,status,allocation,code,data,code_size,state_offset;
    u32 rx_result,write_result,ro_result,installed;
    u32 usb_guard_offset,usb_branch,usb_write_result,usb_ro_result,usb_installed;
};

__attribute__((section(".text.bootstrap")))
void bootstrap_main(void) {
    volatile struct report *s=(void *)0x06b95180;
    s->magic=0x52494e31;
    s->status=1;
    if (!s->code_size || s->code_size>0x600 || s->state_offset%4 ||
        s->state_offset+4>s->code_size ||
        s->usb_guard_offset%4 || s->usb_guard_offset>=s->code_size ||
        WORD(HOOK_IMAGE+s->state_offset)!=0xdeadbeef ||
        WORD(SLOT)!=ORIGINAL || WORD(0x0011c094)!=0x0251ec16 ||
        WORD(0x02240d84)!=0x0affffe2 || WORD(0x0011c088)!=0x0221ec06) {
        s->status=0x80000001; return;
    }
    u32 raw=CALL1(0x013d77a4,0x3000);
    s->allocation=raw;
    if (!raw) { s->status=0x80000002; return; }
    u32 page=(raw+0xfff)&~0xfffU, data=page+0x1000;
    s->code=page; s->data=data;
    if (raw<0x01c00000 || raw>0x01cfd000 || data+0x1000>raw+0x3000 ||
        WORD(0x0011c070)!=0x000a0401) {
        CALL1(0x013d77c4,raw); s->status=0x80000003; return;
    }
    u32 descriptor=WORD(0xa0400+((page>>12)&255)*4);
    if (descriptor!=(page|0x5b7)) {
        CALL1(0x013d77c4,raw); s->status=0x80000004; return;
    }
    for (u32 i=0;i<0x1000;i++) ((u8 *)data)[i]=0;
    for (u32 i=0;i<s->code_size;i++) ((u8 *)page)[i]=((u8 *)HOOK_IMAGE)[i];
    WORD(page+s->state_offset)=data;
    /* Shared state layout is the first 16 words in rec_lifecycle_hook.c. */
    WORD(data)=0x52454348; WORD(data+4)=2;
    WORD(data+8)=raw; WORD(data+12)=page; WORD(data+16)=data;
    WORD(data+40)=ORIGINAL; WORD(data+44)=12; WORD(data+48)=7;
    s->rx_result=(u32)PROTECT(page,0x1000,5);
    if (s->rx_result) { s->status=0x80000005; return; }
    s->write_result=(u32)PROTECT(0x02500000,0x100000,3);
    if (s->write_result) { s->status=0x80000006; return; }
    WORD(SLOT)=page;
    __asm__ volatile("dsb sy" ::: "memory");
    s->installed=1;
    s->ro_result=(u32)PROTECT(0x02500000,0x100000,1);
    if (s->ro_result) { s->status=0x80000007; return; }
    if (WORD(0x0011c094)!=0x0251ec16) { s->status=0x80000008; return; }
    /* A single conditional branch redirects the obsolete boot-Jig decision.
     * Stock startup state is not changed. The guard remains closed until REC. */
    s->usb_branch=0x0b000000|(((page+s->usb_guard_offset-0x02240d8c)>>2)&0xffffff);
    s->usb_write_result=(u32)PROTECT(0x02200000,0x100000,7);
    if (s->usb_write_result) { s->status=0x80000009; return; }
    WORD(0x02240d84)=s->usb_branch;
    __asm__ volatile("dsb sy" ::: "memory");
    s->usb_installed=1;
    s->usb_ro_result=(u32)PROTECT(0x02200000,0x100000,5);
    if (s->usb_ro_result || WORD(0x0011c088)!=0x0221ec06) {
        s->status=0x8000000a; return;
    }
    s->status=2;
}
