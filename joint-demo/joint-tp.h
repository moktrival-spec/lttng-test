#undef LTTNG_UST_TRACEPOINT_PROVIDER
#define LTTNG_UST_TRACEPOINT_PROVIDER control
#undef LTTNG_UST_TRACEPOINT_INCLUDE
#define LTTNG_UST_TRACEPOINT_INCLUDE "./joint-tp.h"
#if !defined(JOINT_TP_H) || defined(LTTNG_UST_TRACEPOINT_HEADER_MULTI_READ)
#define JOINT_TP_H
#include <stdint.h>
#include <lttng/tracepoint.h>
LTTNG_UST_TRACEPOINT_EVENT(control, phase,
    LTTNG_UST_TP_ARGS(const char *, scenario, unsigned int, trial,
                     unsigned int, cycle, const char *, phase,
                     int, actor_tid, uint64_t, release_ns, uint64_t, stamp_ns),
    LTTNG_UST_TP_FIELDS(
        lttng_ust_field_string(scenario, scenario)
        lttng_ust_field_integer(unsigned int, trial, trial)
        lttng_ust_field_integer(unsigned int, cycle, cycle)
        lttng_ust_field_string(phase, phase)
        lttng_ust_field_integer(int, actor_tid, actor_tid)
        lttng_ust_field_integer(uint64_t, release_ns, release_ns)
        lttng_ust_field_integer(uint64_t, stamp_ns, stamp_ns)
    )
)
#endif
#include <lttng/tracepoint-event.h>
