#undef LTTNG_UST_TRACEPOINT_PROVIDER
#define LTTNG_UST_TRACEPOINT_PROVIDER control
#undef LTTNG_UST_TRACEPOINT_INCLUDE
#define LTTNG_UST_TRACEPOINT_INCLUDE "./demo-tp.h"
#if !defined(DEMO_TP_H) || defined(LTTNG_UST_TRACEPOINT_HEADER_MULTI_READ)
#define DEMO_TP_H
#include <stdint.h>
#include <lttng/tracepoint.h>
LTTNG_UST_TRACEPOINT_EVENT(
    control, phase,
    LTTNG_UST_TP_ARGS(unsigned int, cycle, const char *, phase,
                      uint64_t, release_ns, uint64_t, stamp_ns),
    LTTNG_UST_TP_FIELDS(
        lttng_ust_field_integer(unsigned int, cycle, cycle)
        lttng_ust_field_string(phase, phase)
        lttng_ust_field_integer(uint64_t, release_ns, release_ns)
        lttng_ust_field_integer(uint64_t, stamp_ns, stamp_ns)
    )
)
#endif
#include <lttng/tracepoint-event.h>
