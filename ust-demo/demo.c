#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "demo-tp.h"

static volatile uint64_t checksum;
static uint64_t now_ns(void)
{
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t) != 0) {
        perror("clock_gettime");
        exit(EXIT_FAILURE);
    }
    return (uint64_t)t.tv_sec * 1000000000ULL + (uint64_t)t.tv_nsec;
}
static void sleep_until(uint64_t ns)
{
    struct timespec t = {(time_t)(ns / 1000000000ULL),
                         (long)(ns % 1000000000ULL)};
    int error;
    do { error = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &t, NULL); }
    while (error == EINTR);
    if (error != 0) {
        fprintf(stderr, "clock_nanosleep error: %d\n", error);
        exit(EXIT_FAILURE);
    }
}
static void mark(unsigned int cycle, const char *phase, uint64_t release_ns)
{
    uint64_t stamp_ns = now_ns();
    lttng_ust_tracepoint(control, phase, cycle, phase, release_ns, stamp_ns);
}
int main(void)
{
    uint64_t release_ns = now_ns() + 20000000ULL;
    uint64_t value = 1;
    for (unsigned int cycle = 1; cycle <= 10; ++cycle) {
        sleep_until(release_ns);
        mark(cycle, "begin", release_ns);
        for (unsigned int i = 0; i < 12000; ++i) {
            value ^= value << 13;
            value ^= value >> 7;
            value ^= value << 17;
        }
        checksum = value;
        mark(cycle, "compute_end", release_ns);
        /* Simulate a slow output stage in cycle 3; no actual device I/O. */
        sleep_until(now_ns() + (cycle == 3 ? 3000000ULL : 100000ULL));
        mark(cycle, "end", release_ns);
        /* Keep the original schedule, including after an overrun. */
        release_ns += 1000000ULL;
    }
    printf("Completed 10 cycles; checksum=%llu\n", (unsigned long long)checksum);
    return 0;
}
