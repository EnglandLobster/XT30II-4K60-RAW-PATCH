/* Route type 4 -> stock resource profile 6. The route, FPS, sensor and buffer
 * descriptors remain untouched. Apply/restore only while idle in known 30p.
 * Uses the same retained arena and native protection contract as FPS probing.
 */
typedef unsigned int u32;
typedef unsigned char u8;
#define WORD(a) (*(volatile u32 *)(a))
#define BYTE(a) (*(volatile u8 *)(a))
#define PROTECT(a,n,p) (((int (*)(u32,u32,u32))0x0128bc9c)(a,n,p))
#define TARGET 0x02219ed0
#define ORIGINAL 0xe3a00004
#define REPLACEMENT 0xe3a00006
#define RX 0x0221ec06
#define RWX 0x02216c06

struct report {
    u32 magic, action, status, old_value, expected, replacement;
    u32 rw_result, ro_result, writes, value_verified, permissions_verified;
};

static int inactive_root(u32 value) { return value == 0 || value == 0xffffffff; }

__attribute__((section(".text.patch")))
void normal_resource_main(void) {
    volatile struct report *s=(void *)0x01c1e100;
    s->status=1;
    if (s->magic!=0x52535031 || s->action>2 ||
        WORD(0x01c1e000)!=0x52454348 || WORD(0x01c1e004)!=2 ||
        WORD(0x01c1e008)!=0x01c1cf10 || WORD(0x01c1e00c)!=0x01c1d000 ||
        WORD(0x01c1e010)!=0x01c1e000 || WORD(0x01c1e014)!=0 ||
        WORD(0x01c1e018)!=3 || WORD(0x01c1e034)!=0 || WORD(0x01c1e03c)!=0 ||
        BYTE(0x01b7b518)!=3 || BYTE(0x01722b84)!=1 ||
        WORD(0x0011c088)!=RX || WORD(0x0011c070)!=0x000a0401 ||
        WORD(0x000a0478)!=0x01c1e5b6 || WORD(0x013e1788)!=0x7ffffffe ||
        BYTE(0x02cdde60)!=2 || BYTE(0x02cdde61)!=7 || BYTE(0x02e94a30)!=7 ||
        !inactive_root(WORD(0x02e137e8)) || !inactive_root(WORD(0x02e137ec)) ||
        BYTE(0x0177f8eb)!=0 || BYTE(0x0177f8ed)!=3 ||
        BYTE(0x0177f934)!=1 || BYTE(0x0177f935)!=0 ||
        BYTE(0x0177f950)!=1 || BYTE(0x0177f961)!=1 ||
        BYTE(0x01b85ad2)!=4) {
        s->status=0x80000001; return;
    }
    s->expected=s->action==2 ? REPLACEMENT : ORIGINAL;
    s->replacement=s->action==1 ? REPLACEMENT : ORIGINAL;
    s->old_value=WORD(TARGET);
    if (s->old_value!=s->expected) { s->status=0x80000002; return; }
    if (s->action==0) { s->status=2; return; }
    s->rw_result=(u32)PROTECT(0x02200000,0x100000,7);
    if (s->rw_result) { s->status=0x80000003; return; }
    if (WORD(0x0011c088)==RWX) {
        WORD(TARGET)=s->replacement;
        __asm__ volatile("dsb sy" ::: "memory");
        s->writes=1;
        s->value_verified=WORD(TARGET)==s->replacement;
    }
    /* Native API performs the stock SMP, data/instruction-cache and TLB work. */
    s->ro_result=(u32)PROTECT(0x02200000,0x100000,5);
    s->permissions_verified=WORD(0x0011c088)==RX;
    s->status=s->writes && s->value_verified && !s->ro_result &&
        s->permissions_verified ? 2 : 0x80000004;
}
