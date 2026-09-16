// Cacheline ping-pong over shared WB-cacheable memory, two processes, pinned.
// This is the round trip the pc-dimm/cacheable design would achieve; the
// current ivshmem BAR mapping is Normal-NC, so its poll goes to the
// interconnect every iteration instead of hitting L1.
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sched.h>
#include <stdint.h>
#include <time.h>

#define ITERS 20000
struct cell { volatile uint64_t seq; char pad[120]; };

static void pin(int cpu) {
    cpu_set_t s; CPU_ZERO(&s); CPU_SET(cpu, &s);
    if (sched_setaffinity(0, sizeof s, &s)) { perror("affinity"); exit(1); }
    struct sched_param p = { .sched_priority = 1 };
    sched_setscheduler(0, SCHED_FIFO, &p);   /* match the VM demo */
}
static uint64_t ns(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec*1000000000ull + t.tv_nsec;
}
static int cmp(const void *a, const void *b) {
    uint64_t x = *(const uint64_t*)a, y = *(const uint64_t*)b;
    return x < y ? -1 : x > y;
}

int main(int argc, char **argv) {
    if (argc < 4) { fprintf(stderr, "usage: %s <path> <role a|b> <cpu>\n", argv[0]); return 1; }
    int initiator = argv[2][0] == 'a';
    pin(atoi(argv[3]));

    int fd = open(argv[1], O_RDWR | O_CREAT, 0600);
    if (fd < 0) { perror("open"); return 1; }
    if (ftruncate(fd, 4096) && initiator) { perror("ftruncate"); }
    /* no O_SYNC, tmpfs -> normal write-back cacheable */
    void *m = mmap(NULL, 4096, PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0);
    if (m == MAP_FAILED) { perror("mmap"); return 1; }
    struct cell *req = m, *rsp = (struct cell *)((char*)m + 128);
    if (initiator) { req->seq = 0; rsp->seq = 0; }

    uint64_t *lat = malloc(ITERS * sizeof *lat);
    for (uint64_t i = 1; i <= ITERS; i++) {
        if (initiator) {
            uint64_t t0 = ns();
            req->seq = i;
            while (rsp->seq != i) __asm__ volatile("yield" ::: "memory");
            lat[i-1] = ns() - t0;
        } else {
            while (req->seq != i) __asm__ volatile("yield" ::: "memory");
            rsp->seq = i;
        }
    }
    if (initiator) {
        qsort(lat, ITERS, sizeof *lat, cmp);
        printf("cacheable rtt  min %llu ns  p50 %llu ns  p99 %llu ns  max %llu ns  (n=%d)\n",
               (unsigned long long)lat[0], (unsigned long long)lat[ITERS/2],
               (unsigned long long)lat[(int)(ITERS*0.99)], (unsigned long long)lat[ITERS-1], ITERS);
    }
    return 0;
}
