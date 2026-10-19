#undef LTTNG_UST_TRACEPOINT_PROVIDER
#define LTTNG_UST_TRACEPOINT_PROVIDER bench
#undef LTTNG_UST_TRACEPOINT_INCLUDE
#define LTTNG_UST_TRACEPOINT_INCLUDE "./bench-tp.h"
#if !defined(BENCH_TP_H) || defined(LTTNG_UST_TRACEPOINT_HEADER_MULTI_READ)
#define BENCH_TP_H
#include <lttng/tracepoint.h>
LTTNG_UST_TRACEPOINT_EVENT(bench, record,
 LTTNG_UST_TP_ARGS(unsigned long long, seq, unsigned int, worker,
                  unsigned int, phase, unsigned long long, value,
                  unsigned long long, stamp),
 LTTNG_UST_TP_FIELDS(
  lttng_ust_field_integer(unsigned long long, seq, seq)
  lttng_ust_field_integer(unsigned int, worker, worker)
  lttng_ust_field_integer(unsigned int, phase, phase)
  lttng_ust_field_integer(unsigned long long, value, value)
  lttng_ust_field_integer(unsigned long long, stamp, stamp)))
#endif
#include <lttng/tracepoint-event.h>
