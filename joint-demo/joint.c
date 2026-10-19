#define _GNU_SOURCE
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/eventfd.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>
#include "joint-tp.h"

static const char *scenario;
static unsigned int trial;
static int target_cpu, start_fd, gate_fd;
static pthread_barrier_t ready;
static volatile uint64_t checksum;
static uint64_t cycle3_begin, cycle3_end;

static void fail(const char *what) { perror(what); exit(EXIT_FAILURE); }
static void check(int error, const char *what)
{
    if (error) { errno = error; fail(what); }
}
static uint64_t now_ns(void)
{
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) fail("clock_gettime");
    return (uint64_t)t.tv_sec * 1000000000ULL + (uint64_t)t.tv_nsec;
}
static void until(uint64_t ns)
{
    struct timespec t = {(time_t)(ns/1000000000ULL),(long)(ns%1000000000ULL)};
    int e;
    do { e = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &t, NULL); } while(e==EINTR);
    check(e, "clock_nanosleep");
}
static uint64_t mark(unsigned int cycle, const char *phase, uint64_t release)
{
    uint64_t stamp = now_ns();
    lttng_ust_tracepoint(control, phase, scenario, trial, cycle, phase,
                        (int)syscall(SYS_gettid), release, stamp);
    return stamp;
}
static void token(int fd, int writing)
{
    uint64_t value = 1;
    ssize_t n;
    do { n = writing ? write(fd, &value, sizeof(value)) : read(fd, &value, sizeof(value)); }
    while(n<0 && errno==EINTR);
    if(n!=(ssize_t)sizeof(value)) fail("eventfd token");
}
static void setup(const char *name, int priority)
{
    cpu_set_t cpu;
    CPU_ZERO(&cpu); CPU_SET(target_cpu, &cpu);
    check(pthread_setaffinity_np(pthread_self(), sizeof(cpu), &cpu), "affinity");
    check(pthread_setname_np(pthread_self(), name), "thread name");
    struct sched_param sp = {.sched_priority=priority};
    check(pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp), "SCHED_FIFO");
    mark(0,"thread_ready",0);
    int e = pthread_barrier_wait(&ready);
    if(e!=PTHREAD_BARRIER_SERIAL_THREAD) check(e, "barrier");
}
static void *helper(void *unused)
{
    (void)unused;
    setup("supply-70",70);
    token(start_fd,0);
    until(now_ns() + (!strcmp(scenario,"blocked") ? 40000000ULL : 20000000ULL));
    mark(3,"wake_emit",0);
    token(gate_fd,1);
    if(!strcmp(scenario,"ready")) {
        mark(3,"hog_begin",0);
        uint64_t finish = now_ns()+20000000ULL;
        /* Bounded 20 ms CPU hold; never an unbounded FIFO spin. */
        while(now_ns()<finish) __asm__ volatile("" ::: "memory");
        mark(3,"hog_end",0);
    }
    return NULL;
}
static void *control(void *unused)
{
    (void)unused;
    setup("ctrl-loop",50);
    uint64_t release = now_ns()+20000000ULL, value=1;
    for(unsigned int cycle=1;cycle<=10;++cycle) {
        until(release);
        uint64_t begin=mark(cycle,"cycle_begin",release);
        for(unsigned int i=0;i<12000;++i) {
            value^=value<<13; value^=value>>7; value^=value<<17;
        }
        checksum=value;
        if(cycle==3) {
            mark(cycle,"wait_begin",release);
            token(start_fd,1);
            token(gate_fd,0);
            mark(cycle,"wait_end",release);
        }
        uint64_t end=mark(cycle,"cycle_end",release);
        if(cycle==3) { cycle3_begin=begin; cycle3_end=end; }
        release+=1000000ULL;
    }
    return NULL;
}
int main(int argc,char **argv)
{
    if(argc!=4 || (strcmp(argv[1],"blocked") && strcmp(argv[1],"ready"))) {
        fprintf(stderr,"Usage: %s blocked|ready TRIAL CPU\n",argv[0]); return 2;
    }
    scenario=argv[1]; trial=(unsigned int)strtoul(argv[2],NULL,10); target_cpu=atoi(argv[3]);
    if(target_cpu<0 || target_cpu>=CPU_SETSIZE) return 2;
    start_fd=eventfd(0,EFD_CLOEXEC); gate_fd=eventfd(0,EFD_CLOEXEC);
    if(start_fd<0 || gate_fd<0) fail("eventfd");
    check(pthread_barrier_init(&ready,NULL,3),"barrier init");
    pthread_t c,h;
    check(pthread_create(&h,NULL,helper,NULL),"create helper");
    check(pthread_create(&c,NULL,control,NULL),"create control");
    int e=pthread_barrier_wait(&ready);
    if(e!=PTHREAD_BARRIER_SERIAL_THREAD) check(e,"barrier main");
    check(pthread_join(c,NULL),"join control");
    check(pthread_join(h,NULL),"join helper");
    /* Print after both threads finish: these are saved boundary times. */
    printf("scenario=%s trial=%u cycle=3 begin_ns=%llu end_ns=%llu elapsed_ms=%.6f\n",
           scenario,trial,(unsigned long long)cycle3_begin,(unsigned long long)cycle3_end,
           (cycle3_end-cycle3_begin)/1e6);
    close(start_fd);close(gate_fd);pthread_barrier_destroy(&ready);
    return 0;
}
