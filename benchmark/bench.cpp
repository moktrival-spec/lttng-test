#include "bench-tp.h"
#include <spdlog/async.h>
#include <spdlog/sinks/basic_file_sink.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <numeric>
#include <string>
#include <thread>
#include <vector>
#include <sched.h>
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>

static uint64_t now_ns() {
 timespec t{}; clock_gettime(CLOCK_MONOTONIC,&t);
 return uint64_t(t.tv_sec)*1000000000ULL+t.tv_nsec;
}
static void sleep_until(uint64_t t) {
 timespec ts{time_t(t/1000000000ULL),long(t%1000000000ULL)};
 while(clock_nanosleep(CLOCK_MONOTONIC,TIMER_ABSTIME,&ts,nullptr)==EINTR) {}
}
static double cpu_sec() {
 rusage r{}; getrusage(RUSAGE_SELF,&r);
 return r.ru_utime.tv_sec+r.ru_utime.tv_usec*1e-6+r.ru_stime.tv_sec+r.ru_stime.tv_usec*1e-6;
}
static void stats(const char *name,std::vector<uint64_t> v) {
 std::sort(v.begin(),v.end());
 auto q=[&](double p) { return v.at(size_t(std::ceil(p*v.size()))-1); };
 long double sum=0; for(auto n:v)sum+=n;
 std::cout<<"\""<<name<<"\":{\"n\":"<<v.size()<<",\"mean_ns\":"<<double(sum/v.size())
 <<",\"p50_ns\":"<<q(.5)<<",\"p99_ns\":"<<q(.99)<<",\"p999_ns\":"<<q(.999)<<",\"max_ns\":"<<v.back()<<"}";
}
int main(int argc,char **argv) {
 if(argc!=6) { std::cerr<<"mode stages cycles directory queue_slots\n"; return 2; }
 std::string mode=argv[1],dir=argv[4];
 int stages=std::stoi(argv[2]),cycles=std::stoi(argv[3]),nthreads=4,warmup=8;
 size_t slots=std::stoull(argv[5]);
 if(16384%stages) return 3;
 std::shared_ptr<spdlog::details::thread_pool> pool;
 std::shared_ptr<spdlog::sinks::basic_file_sink_mt> sink;
 std::shared_ptr<spdlog::logger> logger;
 if(mode=="sync"||mode=="async-drop"||mode=="async-block"||mode=="spdlog-off") {
  sink=std::make_shared<spdlog::sinks::basic_file_sink_mt>(dir+"/records.csv",true);
  if(mode=="async-drop"||mode=="async-block") {
   pool=std::make_shared<spdlog::details::thread_pool>(slots,1);
   auto policy=mode=="async-drop"?spdlog::async_overflow_policy::discard_new:spdlog::async_overflow_policy::block;
   logger=std::make_shared<spdlog::async_logger>("bench",sink,pool,policy);
  } else logger=std::make_shared<spdlog::logger>("bench",sink);
  logger->set_pattern("%v");
  if(mode=="spdlog-off")logger->set_level(spdlog::level::off);
 }
 std::vector<std::vector<uint64_t>> calls(nthreads),service(nthreads),response(nthreads);
 std::vector<uint64_t> checksum(nthreads),last(nthreads);
 for(int w=0;w<nthreads;++w) {
  calls[w].resize(size_t(cycles)*stages*2,0);service[w].resize(cycles,0);response[w].resize(cycles,0);
 }
 std::atomic<int> ready{0};std::atomic<uint64_t> epoch{0};
 std::atomic<int> failed{0};
 std::vector<std::thread> threads;
 for(int w=0;w<nthreads;++w)threads.emplace_back([&,w] {
  cpu_set_t mask; CPU_ZERO(&mask);CPU_SET(w*2,&mask);
  if(pthread_setaffinity_np(pthread_self(),sizeof(mask),&mask))failed=1;
  uint64_t value=0x12345678ULL+w;size_t call_index=0;
  auto emit=[&](uint64_t seq,unsigned phase,bool measured) {
   uint64_t before=now_ns();
   if(mode=="lttng"||mode=="ust-off") {
    lttng_ust_tracepoint(bench,record,(unsigned long long)seq,(unsigned)w,phase,
                        (unsigned long long)value,(unsigned long long)before);
   } else if(logger)logger->info("{},{},{},{},{}",seq,w,phase,value,before);
   uint64_t after=now_ns();
   if(measured)calls[w][call_index++]=after-before;
  };
  auto body=[&](int c,bool measured) {
   for(int stage=0;stage<stages;++stage) {
    uint64_t seq=(uint64_t(w)*cycles+c)*stages*2+stage*2;
    if(!measured)seq=(1ULL<<63)+(uint64_t(w)*warmup+c)*stages*2+stage*2;
    emit(seq,unsigned(stage*2),measured);
    for(int k=0;k<16384/stages;++k) { value^=value<<13;value^=value>>7;value^=value<<17; }
    emit(seq+1,unsigned(stage*2+1),measured);
   }
  };
  for(int c=0;c<warmup;++c)body(c,false);
  ++ready;
  while(!epoch.load(std::memory_order_acquire))std::this_thread::sleep_for(std::chrono::milliseconds(1));
  uint64_t start=epoch.load();
  for(int c=0;c<cycles;++c) {
   uint64_t release=start+uint64_t(c)*1000000ULL;
   sleep_until(release);uint64_t actual=now_ns();
   body(c,true);uint64_t end=now_ns();
   service[w][c]=end-actual;response[w][c]=end-release;last[w]=end;
  }
  checksum[w]=value;
 });
 while(ready.load()!=nthreads)std::this_thread::sleep_for(std::chrono::milliseconds(1));
 std::this_thread::sleep_for(std::chrono::milliseconds(200));
 std::ofstream(dir+"/ready").put('1');
 while(access((dir+"/go").c_str(),F_OK)!=0)std::this_thread::sleep_for(std::chrono::milliseconds(1));
 double cpu0=cpu_sec();uint64_t start=now_ns()+100000000ULL;
 epoch.store(start,std::memory_order_release);
 for(auto &t:threads)t.join();
 size_t dropped=pool?pool->discard_counter():0;
 size_t queued=pool?pool->queue_size():0;
 logger.reset();pool.reset(); // joins worker after queued records have been processed
 if(sink)sink->flush();
 uint64_t drained=now_ns();double cpu1=cpu_sec();
 std::vector<uint64_t> allcalls,allservice,allresponse;
 for(int w=0;w<nthreads;++w) {
  allcalls.insert(allcalls.end(),calls[w].begin(),calls[w].end());
  allservice.insert(allservice.end(),service[w].begin(),service[w].end());
  allresponse.insert(allresponse.end(),response[w].begin(),response[w].end());
 }
 size_t misses=std::count_if(allresponse.begin(),allresponse.end(),[](uint64_t n){return n>1000000;});
 std::cout<<"{\"mode\":\""<<mode<<"\",\"stages\":"<<stages<<",\"cycles_per_thread\":"<<cycles
 <<",\"threads\":4,\"warmup_cycles\":8,\"expected_measured\":"<<uint64_t(cycles)*stages*2*4
 <<",\"expected_warmup\":"<<uint64_t(warmup)*stages*2*4
 <<",\"async_msg_bytes\":"<<sizeof(spdlog::details::async_msg)<<",\"queue_slots\":"<<slots
 <<",\"discard_counter\":"<<dropped<<",\"queue_at_producer_end\":"<<queued
 <<",\"deadline_misses\":"<<misses<<",\"self_cpu_s\":"<<cpu1-cpu0
 <<",\"producer_wall_s\":"<<(*std::max_element(last.begin(),last.end())-start)/1e9
 <<",\"drained_wall_s\":"<<(drained-start)/1e9<<",\"affinity_ok\":"<<(failed?"false":"true")
 <<",\"checksum\":"<<std::accumulate(checksum.begin(),checksum.end(),uint64_t(0))<<",";
 stats("call",std::move(allcalls));std::cout<<",";stats("service",std::move(allservice));std::cout<<",";
 stats("response",std::move(allresponse));std::cout<<"}\n";
 return failed?4:0;
}
