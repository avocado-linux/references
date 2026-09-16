/*
 * shmdemo -- PID 1 for the two demo guests.
 *
 * Both VMs are handed the SAME host file (/dev/shm/...) as an ivshmem-plain
 * BAR. Mapping that BAR puts the identical host pages into both guests'
 * address spaces, so a value one guest stores is visible to the other with no
 * copy, no hypercall, and no syscall after the initial mmap(). That is the
 * whole claim being measured here: the payload is written once, read once, and
 * never transits a buffer owned by anyone else.
 *
 * Roles (from the kernel cmdline, shm.role=):
 *   ping  publishes into its half of the region, then waits for the echo and
 *         records the round trip on its own counter
 *   pong  waits for a publish, reads it back, answers in its own half
 *
 * Round trip rather than one-way on purpose. A one-way number needs a time
 * base both guests agree on, and KVM gives each VM its own CNTVOFF_EL2, so
 * CNTVCT_EL0 in guest A and guest B are not comparable -- subtracting them
 * would produce a confident, wrong answer. RTT is measured entirely on the
 * initiator's own counter and needs no agreement at all.
 *
 * Runs as init, so it mounts what it needs and never returns.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/mman.h>
#include <sys/reboot.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

/* Red Hat / virtio vendor, ivshmem device. */
/* Must match the reserved-memory node in guest-dt/avocado-shm.dtso and the
 * NUMA node size launch-vm passes to qemu. 64 MiB. */
#define SHM_REGION_BYTES (64u * 1024u * 1024u)

#define IVSHMEM_VENDOR 0x1af4
#define IVSHMEM_DEVICE 0x1110

/* Control block in the first page; payload halves after a 64 KiB gap so a
 * runaway write to the control block cannot silently land in payload. */
#define CTL_MAGIC   0x41564f53484d3031ULL  /* "AVOSHM01" */
#define BUF_OFF     65536u

/*
 * One control word per cache line.
 *
 * The obvious layout -- C_PING = 1, C_PONG = 2 -- puts both sequence counters
 * in the same 64-byte line. Each side writes its own counter and polls the
 * peer's, so on that layout every write invalidates the line the peer is
 * spinning on, and the poll that should be an L1 hit becomes a coherency miss
 * that has to pull the line back from the other core. The two counters are
 * logically independent and were being made to share a line for no reason:
 * textbook false sharing, and it costs a full cross-core transfer on the
 * measured path, twice per round trip.
 *
 * Indices are 8 apart because the words are 8 bytes and the line is 64: these
 * are Cortex-A78AE cores (MIDR CPU part 0xd4b, confirmed on the board), and
 * every A78 variant has a 64-byte line. Do not try to read this out of sysfs
 * at runtime -- coherency_line_size is absent under this DT-described cache
 * hierarchy, which is why it is a constant with an assert rather than a probe. C_MAGIC and C_BYTES stay together in line 0 -- both are
 * written once during setup and never touched on the measured path, so they
 * cannot false-share with anything that matters. C_PONG_UP gets its own line
 * rather than riding along with them: it is only read during startup, but it
 * is read by the same spin loop that later polls C_PONG, and keeping the
 * startup handshake out of the steady-state lines costs nothing here.
 *
 * Measured on the development board, 8-byte payload, guest to guest (dmb ish throughout):
 *   shared line   min 208 ns  p50 260 ns
 *   split lines   min 208 ns  p50 260 ns
 *
 * No measurable change, and that is the expected result rather than a
 * disappointment: a line transfer between two cores in this cluster costs
 * something like 20-40 ns, and the counter this demo times with ticks at
 * 52 ns, so the win is real but lands entirely inside one tick. It is kept
 * because it is free and because it is the correct layout -- under real
 * contention, or on a part with a finer counter, it stops being invisible.
 * Do not "simplify" it back to adjacent indices on the grounds that the
 * numbers did not move; they did not move because the clock cannot see them.
 */
#define CACHE_LINE  64u
#define CTL_STRIDE  (CACHE_LINE / sizeof(uint64_t))   /* 8 words per line */

enum {
    C_MAGIC   = 0,
    C_BYTES   = 1,
    C_PING    = 1 * CTL_STRIDE,   /* byte 64  */
    C_PONG    = 2 * CTL_STRIDE,   /* byte 128 */
    C_PONG_UP = 3 * CTL_STRIDE,   /* byte 192 */
};

/* The control block is the first BUF_OFF bytes; the payload starts after it.
 * If a future field pushes past that, it lands in payload and corrupts it
 * silently, so fail the build instead. */
_Static_assert((C_PONG_UP + 1) * sizeof(uint64_t) <= BUF_OFF,
               "control block outgrew BUF_OFF");
_Static_assert(CACHE_LINE % sizeof(uint64_t) == 0, "stride is not whole words");

/*
 * Plain volatile 64-bit loads/stores plus explicit barriers -- deliberately
 * NOT __atomic_*.
 *
 * If the BAR ends up mapped as Device-nGnRE (the arm64 default for a PCI
 * resource that is not marked prefetchable), the exclusive monitor
 * instructions that __atomic_* compiles to are architecturally not permitted
 * on that memory type and fault. Aligned single-copy 64-bit accesses are
 * permitted on both Device and Normal memory, and a dsb between the payload
 * write and the sequence store is enough ordering for a single-producer
 * handshake, so this works whichever mapping we get.
 */
/*
 * dmb ish, not dsb sy.
 *
 * dsb sy is a full-system COMPLETION barrier, and it was the right choice when
 * this mapping could be Device-nGnRE: completion is what device memory needs.
 * On the cacheable mapping the peer is another core in the same
 * inner-shareable domain, so ordering -- not completion -- is what the
 * handshake requires, and dmb ish is the cheapest barrier that provides it.
 *
 * Measured on the development board, 8-byte payload, guest to guest:
 *   dsb sy   min 260 ns  p50 260 ns
 *   dmb ish  min 208 ns  p50 260 ns
 *
 * Read those with the clock in mind. The guest's arch counter runs at
 * 19.2 MHz, so one tick is 52 ns and the whole round trip is four to five
 * ticks. dmb ish takes one tick off the minimum -- which lands exactly on the
 * 208 ns bare-metal host baseline -- and p50 cannot move without resolving a
 * sub-tick difference this counter cannot report. Do not read anything into a
 * 52 ns delta between two runs: that is one tick, and it is the noise floor.
 *
 * Kept as one macro rather than switched on the mapping: dmb ish is also
 * sufficient for the Normal-NC fallback path, since that is still Normal
 * memory in the same shareability domain. It would NOT be sufficient for
 * Device-nGnRE, which is why the fallback prefers resource2_wc.
 */
#define BARRIER() __asm__ volatile("dmb ish" ::: "memory")

/*
 * Spin, then back off.
 *
 * A bare busy-poll is exactly right for the microseconds a peer takes to answer
 * inside a run, and ruinous between runs. The loop runs at SCHED_FIFO in the
 * guest, so the host's vCPU thread is runnable 100% of the time; and on a
 * PREEMPT_RT host the per-CPU kernel threads that RCU depends on -- rcuc/N,
 * ktimers/N -- are themselves SCHED_FIFO priority 1. An equal-priority FIFO
 * task is run-to-completion against them, so they never get the CPU.
 *
 * Measured, with the responder polling straight through the initiator's 10s
 * sleep: "rcu: INFO: rcu_preempt self-detected stall on CPU 5" every ~21s,
 * after which PID 1 stopped answering -- sshd could not complete a banner
 * exchange and every systemctl hung, while ICMP still replied. The board needed
 * a reset. Nothing about that is specific to this demo: any guest that
 * busy-polls forever at RT priority does it.
 *
 * SPIN_BUDGET is counted in loop iterations. On the cacheable mapping each
 * iteration is an L1 hit -- the peer's sequence line stays in the local cache
 * until the peer's write invalidates it -- so an iteration costs a couple of
 * nanoseconds and the budget is ~150 us of tight spinning, not the ~15 ms it
 * was when every poll was an uncached ~150 ns read of the BAR. That is still
 * more than an order of magnitude past the ~10 us worst-case round trip
 * measured here, so the backoff still cannot fire on the measured path; it
 * only yields sooner once a peer has gone quiet, which is exactly what the RCU
 * stall above wanted. Then this thread sleeps in 200 us slices and the host's
 * RCU machinery gets its CPU back.
 *
 * Callers reset the counter the moment work arrives, so a slow round trip can
 * never accumulate its way into the sleeping state.
 */
#define SPIN_BUDGET 100000ULL
#define BACKOFF_NS  200000L

static inline void spin_backoff(unsigned long long *spins)
{
    if (++*spins < SPIN_BUDGET)
        return;
    struct timespec ts = { .tv_sec = 0, .tv_nsec = BACKOFF_NS };
    nanosleep(&ts, NULL);
}

static inline void     st64(volatile uint64_t *p, uint64_t v) { *p = v; }
static inline uint64_t ld64(volatile uint64_t *p)             { return *p; }

#define PAT_MUL 0x9E3779B97F4A7C15ULL

/*
 * Payload accessors -- deliberately NOT st64/ld64.
 *
 * volatile is right for the control words: the compiler must never cache,
 * merge, reorder or elide a handshake store. It is the wrong tool for the
 * payload, and it is not free -- volatile forbids vectorisation, so a
 * 4096-byte payload compiled to 512 separate single-word stores that no NEON
 * pair could ever cover. That was the throughput ceiling, not the memory.
 *
 * Dropping volatile here does not weaken the protocol by one bit. Ordering
 * between the payload and the sequence bump comes from BARRIER(), whose
 * "memory" clobber is a full compiler barrier in both directions: every
 * payload store before it must be materialised, and no load after it may be
 * hoisted above it. That is precisely the guarantee the handshake needs.
 * volatile was never a synchronisation primitive; the barrier is.
 */
static inline void payload_pattern(volatile uint64_t *dst, uint64_t words,
                                   uint64_t seed)
{
    uint64_t *d = (uint64_t *)dst;
    for (uint64_t w = 0; w < words; w++)
        d[w] = seed ^ (w * PAT_MUL);
}

static inline void payload_const(volatile uint64_t *dst, uint64_t words,
                                 uint64_t v)
{
    uint64_t *d = (uint64_t *)dst;
    for (uint64_t w = 0; w < words; w++)
        d[w] = v;
}

static inline void payload_touch(const volatile uint64_t *src, uint64_t words)
{
    const uint64_t *p = (const uint64_t *)src;
    uint64_t sum = 0;
    for (uint64_t w = 0; w < words; w++)
        sum += p[w];
    /* With volatile gone the compiler may delete a loop whose result nothing
     * uses -- and deleting it would mean the responder never actually reads
     * the shared pages this demo exists to measure. Consuming the sum in an
     * asm operand pins the loop in place and emits no instruction. */
    __asm__ volatile("" :: "r"(sum));
}

static inline uint64_t cntvct(void)
{
    uint64_t v;
    __asm__ volatile("isb; mrs %0, cntvct_el0" : "=r"(v) :: "memory");
    return v;
}

static inline uint64_t cntfrq(void)
{
    uint64_t v;
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(v));
    return v;
}

/*
 * The guest kernel is PREEMPT_RT, so make the measuring thread actually
 * real-time rather than just hoping.
 *
 * SCHED_FIFO: the ping/pong loop busy-polls a shared word, so as SCHED_OTHER
 * it is preemptible by anything the guest decides to run -- its own timer tick,
 * kworkers, journald-equivalents -- and every one of those shows up directly in
 * the round-trip tail, not the median. FIFO at a priority above the guest's
 * housekeeping removes that class of outlier.
 *
 * mlockall: the region is already resident (it is a PCI BAR mapping), but the
 * stack, the sample array and the binary itself are not. A minor fault mid-loop
 * is microseconds of tail for no reason.
 *
 * Both are best-effort and report rather than abort: an unprivileged or
 * differently-configured guest should still produce numbers, just noisier ones.
 */
static void go_realtime(void)
{
    struct sched_param sp;
    sp.sched_priority = 80;

    if (sched_setscheduler(0, SCHED_FIFO, &sp) != 0)
        fprintf(stderr, "shmdemo: SCHED_FIFO failed (%s), staying SCHED_OTHER\n",
                strerror(errno));
    else
        printf("shmdemo: scheduling  SCHED_FIFO prio %d\n", sp.sched_priority);

    if (mlockall(MCL_CURRENT | MCL_FUTURE) != 0)
        fprintf(stderr, "shmdemo: mlockall failed (%s)\n", strerror(errno));
    else
        printf("shmdemo: memory      locked (mlockall)\n");

    /*
     * Disable RT throttling, which SCHED_FIFO above would otherwise walk
     * straight into.
     *
     * The responder busy-polls a shared word forever. The kernel's default
     * RT bandwidth control (sched_rt_runtime_us 950000 of a 1000000 period)
     * exists precisely to stop a runaway RT task wedging a CPU, and it does so
     * by refusing to schedule it for the remaining 5% -- a ~50 ms stall every
     * second, which as far as the initiator can tell is a 50 ms round trip.
     *
     * Safe here and only here: this is a single-purpose guest with one CPU and
     * nothing else to starve, and the whole point of the VM is to run this one
     * loop. On a general-purpose system leave the throttle alone.
     */
    int fd = open("/proc/sys/kernel/sched_rt_runtime_us", O_WRONLY);
    if (fd >= 0) {
        if (write(fd, "-1", 2) == 2)
            printf("shmdemo: rt throttle disabled\n");
        close(fd);
    }
}

static void die(const char *msg)
{
    fprintf(stderr, "shmdemo: %s\n", msg);
    fflush(NULL);
    sleep(5);
    reboot(RB_POWER_OFF);
    _exit(1);
}

/* --- boot ------------------------------------------------------------- */

/* The kernel only wires up init's stdio from a /dev/console that already
 * exists in the initramfs, and a cpio built as an unprivileged user cannot
 * carry device nodes. Mount devtmpfs ourselves and claim the console, so the
 * demo output reaches the serial port (and from there the host's journal). */
static void early_init(void)
{
    mkdir("/dev", 0755);
    mkdir("/proc", 0755);
    mkdir("/sys", 0755);
    mount("devtmpfs", "/dev", "devtmpfs", 0, NULL);
    mount("proc", "/proc", "proc", 0, NULL);
    mount("sysfs", "/sys", "sysfs", 0, NULL);

    int fd = open("/dev/console", O_RDWR);
    if (fd >= 0) {
        dup2(fd, 0);
        dup2(fd, 1);
        dup2(fd, 2);
        if (fd > 2)
            close(fd);
    }
    setvbuf(stdout, NULL, _IOLBF, 0);
}

static int read_small(const char *path, char *buf, size_t n)
{
    int fd = open(path, O_RDONLY);
    if (fd < 0)
        return -1;
    ssize_t got = read(fd, buf, n - 1);
    close(fd);
    if (got < 0)
        return -1;
    buf[got] = '\0';
    return 0;
}

/*
 * Copy the value of `key=` from the kernel cmdline into `out`, or `def` if the
 * key is absent.
 *
 * The caller supplies the buffer, deliberately. An earlier version returned a
 * pointer to a function-static buffer, which aliased: main() read shm.role and
 * then shm.iters and shm.payload, each call overwriting the one buffer, so by
 * the time the role was used it held the last value parsed. Both guests read
 * their role as "4096", neither matched "ping", both took the pong branch, and
 * the demo deadlocked with two responders and no initiator -- printing a
 * cheerful "role=4096" on the way.
 */
static void cmdline_str(const char *key, char *out, size_t n, const char *def)
{
    static char cmdline[4096];
    static int loaded = 0;

    if (!loaded) {
        if (read_small("/proc/cmdline", cmdline, sizeof cmdline) < 0)
            cmdline[0] = '\0';
        loaded = 1;
    }

    size_t klen = strlen(key);
    for (char *p = cmdline; *p; ) {
        while (*p == ' ' || *p == '\n')
            p++;
        if (!strncmp(p, key, klen) && p[klen] == '=') {
            char *v = p + klen + 1;
            size_t i = 0;
            while (v[i] && v[i] != ' ' && v[i] != '\n' && i + 1 < n) {
                out[i] = v[i];
                i++;
            }
            out[i] = '\0';
            return;
        }
        while (*p && *p != ' ' && *p != '\n')
            p++;
    }
    snprintf(out, n, "%s", def ? def : "");
}

static uint64_t cmdline_u64(const char *key, uint64_t def)
{
    char buf[64];
    cmdline_str(key, buf, sizeof buf, "");
    return buf[0] ? strtoull(buf, NULL, 0) : def;
}

/* --- device ----------------------------------------------------------- */

/*
 * Load the guest shared-memory driver and map its region write-back cacheable.
 *
 * This is the fast path, and the reason it exists: an ivshmem PCI BAR cannot
 * be mapped cacheably on arm64. resource2 gets Device-nGnRE and resource2_wc
 * gets Normal-NC, so every poll iteration below is an interconnect round trip
 * (~150-190 ns) instead of an L1 hit. Measured on the development board, same ping-pong:
 * 7187 ns p50 through the BAR against 208 ns over cacheable memory.
 *
 * The region arrives as a second cold NUMA node backed by the shared file, is
 * marked reserved-memory in the guest device tree WITHOUT `no-map` (so it
 * stays in the linear map and can therefore be cached), and avocado-shm.ko
 * hands out exactly that window via remap_pfn_range() with a default
 * vm_page_prot.
 *
 * finit_module() rather than insmod: the initramfs holds one file and this
 * binary is init, so there is no shell to load it from.
 */
static int load_shm_module(void)
{
    int fd = open("/avocado-shm.ko", O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return -1;
    int ret = (int)syscall(__NR_finit_module, fd, "", 0);
    close(fd);
    /* EEXIST means someone already loaded it, which is success for us. */
    if (ret < 0 && errno != EEXIST)
        return -1;
    return 0;
}

static void *map_cacheable(size_t *out_len, const char **out_how)
{
    if (load_shm_module() < 0) {
        printf("shmdemo: avocado-shm.ko not loaded (%s); falling back to the BAR\n",
               strerror(errno));
        return NULL;
    }
    int fd = open("/dev/avocado-shm", O_RDWR | O_CLOEXEC);
    if (fd < 0) {
        printf("shmdemo: /dev/avocado-shm absent (%s); falling back to the BAR\n",
               strerror(errno));
        return NULL;
    }
    /*
     * No O_SYNC and no PROT_ hints that would downgrade the attributes: the
     * driver's mapping is already Normal write-back, and the whole point is
     * to keep it that way.
     */
    size_t len = (size_t)SHM_REGION_BYTES;
    void *pv = mmap(NULL, len, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (pv == MAP_FAILED) {
        printf("shmdemo: mmap of /dev/avocado-shm failed (%s); falling back\n",
               strerror(errno));
        return NULL;
    }
    *out_len = len;
    *out_how = "cacheable (avocado-shm)";
    printf("shmdemo: mapped /dev/avocado-shm, %zu MiB, write-back cacheable\n",
           len >> 20);
    return pv;
}

/*
 * Map the ivshmem BAR with no driver in the way: nothing in mainline claims
 * 1af4:1110, so its BARs stay available through PCI sysfs. resource2_wc is
 * tried first because a write-combining mapping is enormously faster than the
 * Device-nGnRE that a plain resource2 mmap gets on arm64 -- and which mapping
 * we actually get is the single biggest factor in the numbers below, so the
 * choice is reported rather than assumed.
 */
static void *map_ivshmem(size_t *out_len, const char **out_how)
{
    DIR *d = opendir("/sys/bus/pci/devices");
    if (!d)
        die("no /sys/bus/pci/devices (is sysfs mounted?)");

    struct dirent *e;
    while ((e = readdir(d))) {
        if (e->d_name[0] == '.')
            continue;

        char path[512], buf[64];
        snprintf(path, sizeof path, "/sys/bus/pci/devices/%s/vendor", e->d_name);
        if (read_small(path, buf, sizeof buf) < 0)
            continue;
        if (strtoul(buf, NULL, 16) != IVSHMEM_VENDOR)
            continue;

        snprintf(path, sizeof path, "/sys/bus/pci/devices/%s/device", e->d_name);
        if (read_small(path, buf, sizeof buf) < 0)
            continue;
        if (strtoul(buf, NULL, 16) != IVSHMEM_DEVICE)
            continue;

        static const char *bars[] = { "resource2_wc", "resource2" };
        for (unsigned i = 0; i < 2; i++) {
            snprintf(path, sizeof path, "/sys/bus/pci/devices/%s/%s",
                     e->d_name, bars[i]);
            int fd = open(path, O_RDWR | O_SYNC);
            if (fd < 0)
                continue;
            struct stat st;
            if (fstat(fd, &st) < 0 || st.st_size <= 0) {
                close(fd);
                continue;
            }
            void *p = mmap(NULL, (size_t)st.st_size, PROT_READ | PROT_WRITE,
                           MAP_SHARED, fd, 0);
            close(fd);
            if (p == MAP_FAILED)
                continue;
            closedir(d);
            *out_len = (size_t)st.st_size;
            *out_how = bars[i];
            printf("shmdemo: ivshmem at %s, BAR2 %zu MiB via %s\n",
                   e->d_name, (size_t)st.st_size >> 20, bars[i]);
            return p;
        }
    }
    closedir(d);
    die("no ivshmem device (1af4:1110) found");
    return NULL;
}

/* --- stats ------------------------------------------------------------ */

static int cmp_u64(const void *a, const void *b)
{
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return (x > y) - (x < y);
}

static uint64_t ticks_to_ns(uint64_t ticks, uint64_t hz)
{
    return hz ? (ticks * 1000000000ULL) / hz : 0;
}

/* --- roles ------------------------------------------------------------ */

static void run_ping(volatile uint64_t *ctl, volatile uint64_t *tx,
                     volatile uint64_t *rx, uint64_t words,
                     uint64_t iters, uint64_t hz)
{
    uint64_t *samples = calloc(iters, sizeof *samples);
    if (!samples)
        die("out of memory for samples");

    st64(&ctl[C_BYTES], words * 8);
    st64(&ctl[C_MAGIC], CTL_MAGIC);
    BARRIER();

    printf("shmdemo: ping waiting for pong to come up...\n");
    {
        unsigned long long spins = 0;
        while (ld64(&ctl[C_PONG_UP]) != 1)
            spin_backoff(&spins);
    }
    printf("shmdemo: pong is up; %llu iterations of %llu bytes\n",
           (unsigned long long)iters, (unsigned long long)(words * 8));

    /*
     * Warm up before recording.
     *
     * The first iterations are not measuring the transport: the guest has just
     * booted, the BAR mapping has never been touched, the write-combining
     * buffers are cold, and the responder may not yet be spinning tightly. Left
     * in the sample set they land as a handful of enormous outliers that move
     * `max` by an order of magnitude between otherwise identical runs while
     * min/p50/p99 do not budge -- which is exactly what was observed before
     * this existed, and is a measurement artifact rather than a property of the
     * system under test.
     *
     * The full distribution is still reported honestly below: the index of the
     * worst sample and the count of samples past 10x the median are printed, so
     * a genuine tail cannot hide behind the warmup.
     */
    uint64_t warmup = iters / 10;
    if (warmup < 100)
        warmup = 100;
    printf("shmdemo: warming up %llu iterations\n", (unsigned long long)warmup);
    /* Reset every iteration, so this only ever fires if the responder has
     * stopped answering entirely -- a dead peer must not turn into a wedged
     * host. It is not free on the measured path: one increment and compare per
     * poll costs about 1-5% of the median, 5416 ns with a bare spin against
     * 5468-5677 ns with this, across eight runs. Worth it -- the bare spin is
     * what stalled RCU and took PID 1 down with it. */
    unsigned long long spins = 0;
    for (uint64_t w = 0; w < warmup; w++) {
        uint64_t seq = w + 1;
        payload_const(tx, words, seq);
        BARRIER();
        st64(&ctl[C_PING], seq);
        while (ld64(&ctl[C_PONG]) != seq)
            spin_backoff(&spins);
        spins = 0;
        BARRIER();
    }

    /*
     * How much of the reported rtt is the clock?
     *
     * Every sample below is t1-t0 across two CNTVCT_EL0 reads, so the read
     * cost is inside the number. At 19.2 MHz one tick is 52 ns and the
     * 8-byte round trip is only four or five ticks, which makes that cost a
     * material fraction rather than a rounding detail -- so measure it here
     * and print it, instead of quietly reporting a latency that includes it.
     *
     * Back-to-back reads with nothing between them: whatever this says is the
     * floor no sample can go below, and the subtraction the reader needs to do
     * for themselves. VHE means the guest reads the counter without trapping,
     * so this stays small, but "should be small" is not a measurement.
     */
    {
        uint64_t best = ~0ULL, cal[256];
        for (int k = 0; k < 256; k++) {
            uint64_t a = cntvct();
            uint64_t b = cntvct();
            cal[k] = b - a;
        }
        for (int k = 0; k < 256; k++)
            if (cal[k] < best)
                best = cal[k];
        qsort(cal, 256, sizeof *cal, cmp_u64);
        printf("shmdemo: timer read   %llu ns min, %llu ns p50 "
               "(included in every rtt below)\n",
               (unsigned long long)ticks_to_ns(best, hz),
               (unsigned long long)ticks_to_ns(cal[128], hz));
    }

    uint64_t t_start = cntvct();
    uint64_t mismatches = 0;

    for (uint64_t i = warmup + 1; i <= warmup + iters; i++) {
        /* Publish. The payload is written straight into the shared pages --
         * this store IS the transfer, there is no send() after it. */
        payload_pattern(tx, words, i);

        BARRIER();              /* payload visible before the sequence bump */
        uint64_t t0 = cntvct();
        st64(&ctl[C_PING], i);

        while (ld64(&ctl[C_PONG]) != i)
            spin_backoff(&spins);
        spins = 0;
        uint64_t t1 = cntvct();
        BARRIER();              /* sequence seen before we read the answer */

        /* Spot-check the echo rather than re-reading the whole buffer, so the
         * measured cost stays the handshake and not our own verification. */
        if (ld64(&rx[0]) != (i + 1) || ld64(&rx[words - 1]) != (i + 1))
            mismatches++;

        samples[i - warmup - 1] = t1 - t0;
    }

    uint64_t t_end = cntvct();

    /* Where the worst sample fell, and how many are genuinely far out. Kept
     * before the sort, since sorting destroys the ordering. */
    uint64_t worst = 0, worst_at = 0;
    for (uint64_t i = 0; i < iters; i++)
        if (samples[i] > worst) { worst = samples[i]; worst_at = i + 1; }

    qsort(samples, iters, sizeof *samples, cmp_u64);
    uint64_t p50t = samples[iters / 2];
    uint64_t outliers = 0;
    for (uint64_t i = 0; i < iters; i++)
        if (samples[i] > p50t * 10)
            outliers++;

    uint64_t elapsed_ns = ticks_to_ns(t_end - t_start, hz);
    /* Each iteration moves the payload twice: written by ping, read by pong,
     * then the same again in the other direction. */
    double mib = (double)iters * (double)(words * 8) * 2.0 / (1024.0 * 1024.0);

    printf("\n");
    printf("shmdemo: === zero-copy round trip ===\n");
    printf("shmdemo: iterations   %llu\n", (unsigned long long)iters);
    printf("shmdemo: payload      %llu bytes\n", (unsigned long long)(words * 8));
    printf("shmdemo: counter      %llu Hz\n", (unsigned long long)hz);
    /* The tick is the resolution of every rtt below it. At 19.2 MHz that is
     * 52 ns against a round trip of a few hundred, so quote it -- otherwise
     * the next reader mistakes one tick of quantisation for a real change. */
    printf("shmdemo: tick         %llu ns\n", (unsigned long long)(1000000000ULL / hz));
    printf("shmdemo: rtt min      %llu ns\n",
           (unsigned long long)ticks_to_ns(samples[0], hz));
    printf("shmdemo: rtt p50      %llu ns\n",
           (unsigned long long)ticks_to_ns(samples[iters / 2], hz));
    printf("shmdemo: rtt p99      %llu ns\n",
           (unsigned long long)ticks_to_ns(samples[(iters * 99) / 100], hz));
    printf("shmdemo: rtt max      %llu ns (at measured iteration %llu of %llu)\n",
           (unsigned long long)ticks_to_ns(samples[iters - 1], hz),
           (unsigned long long)worst_at, (unsigned long long)iters);
    printf("shmdemo: outliers     %llu of %llu past 10x p50\n",
           (unsigned long long)outliers, (unsigned long long)iters);
    printf("shmdemo: throughput   %.1f MiB/s\n",
           elapsed_ns ? mib / ((double)elapsed_ns / 1e9) : 0.0);
    printf("shmdemo: mismatches   %llu\n", (unsigned long long)mismatches);
    printf("shmdemo: ==========================================\n\n");

    free(samples);
}

static void run_pong(volatile uint64_t *ctl, volatile uint64_t *tx,
                     volatile uint64_t *rx, uint64_t words)
{
    printf("shmdemo: pong waiting for ping to publish the layout...\n");
    {
        unsigned long long spins = 0;
        while (ld64(&ctl[C_MAGIC]) != CTL_MAGIC)
            spin_backoff(&spins);
    }
    BARRIER();

    st64(&ctl[C_PONG_UP], 1);
    BARRIER();
    printf("shmdemo: pong ready, echoing\n");

    uint64_t last = 0;
    unsigned long long spins = 0;
    for (;;) {
        uint64_t seq;
        while ((seq = ld64(&ctl[C_PING])) == last)
            spin_backoff(&spins);
        spins = 0;              /* work arrived: back to tight spinning */
        BARRIER();              /* sequence seen before we read the payload */

        /* Read the payload in place. Nothing is copied out; the sum exists
         * only to prove every word was actually fetched from shared memory. */
        payload_touch(rx, words);

        payload_const(tx, words, seq + 1);

        BARRIER();
        st64(&ctl[C_PONG], seq);
        last = seq;
    }
}

int main(void)
{
    early_init();
    go_realtime();

    char role[32];
    cmdline_str("shm.role", role, sizeof role, "pong");
    uint64_t iters   = cmdline_u64("shm.iters", 20000);
    uint64_t payload = cmdline_u64("shm.payload", 4096);

    size_t len;
    const char *how;
    /* Cacheable first, BAR second. The fallback is not vestigial: a target
     * without the guest module or the reserved-memory node still runs the
     * demo, just at interconnect speed -- and printing `how` is what makes the
     * two regimes distinguishable in the results below. */
    volatile uint64_t *base = map_cacheable(&len, &how);
    if (!base)
        base = map_ivshmem(&len, &how);

    if (len <= BUF_OFF + 64)
        die("ivshmem region too small");

    /* Two equal halves after the control page: one direction each, so neither
     * side ever writes where the other is reading. */
    size_t half = (len - BUF_OFF) / 2;
    if (payload > half)
        payload = half;
    uint64_t words = payload / 8;
    if (words == 0)
        die("payload smaller than one word");

    volatile uint64_t *ctl = base;
    volatile uint64_t *a   = (volatile uint64_t *)((char *)base + BUF_OFF);
    volatile uint64_t *b   = (volatile uint64_t *)((char *)base + BUF_OFF + half);

    uint64_t hz = cntfrq();
    printf("shmdemo: role=%s payload=%llu iters=%llu region=%zu MiB\n",
           role, (unsigned long long)(words * 8),
           (unsigned long long)iters, len >> 20);

    if (!strcmp(role, "ping")) {
        /* ping writes half A, reads half B */
        for (;;) {
            run_ping(ctl, a, b, words, iters, hz);
            printf("shmdemo: sleeping 10s, then running again\n");
            sleep(10);
        }
    } else {
        /* pong writes half B, reads half A */
        run_pong(ctl, b, a, words);
    }

    reboot(RB_POWER_OFF);
    return 0;
}
