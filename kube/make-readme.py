# -*- coding: utf-8 -*-
import sqlite3
import numpy
import StringIO

conn = sqlite3.connect('dnsperf.db')
cursor = conn.cursor()

dnsmasq_cache = ['0', '10000']
kubedns_cpu = ['200m', '250m', '']
dnsmasq_cpu = ['100m', '200m', '250m', '']
query_type = ['nx-domain', 'outside', 'pod-ip', 'service']
max_qps = ['-Q500', '-Q1000', '-Q2000', '-Q3000', '']

headings = (
    'cached', 'kubedns_cpu', 'dnsmasq_cpu', 'query_type', 'target QPS',
    'attained QPS', 'avg latency (ms)', 'max (ms)',
    '50%tile', '95%tile', '99%tile', '99.5%tile'
    )

out = StringIO.StringIO()

out.write("""
# Overview

This directory contains scripts used to run a dns performance test
against a kubernetes cluster.

See ./run-dnsperf.sh --help for details on how to rerun the benchmark
on your own cluster.

# Raw data

The results below were obtained from a cluster consisting of
2-vCPUs/node. Available RAM was not a factor in the performance test.

## Notes on interpretation

The questions we want to answer:

* What is the maximum QPS we can get from the Kubernetes DNS service
  given no limits?
* If we restrict CPU resources, what is the peformance we can expect?
  (i.e. resource limits in the pod yaml).
* What are the SLOs (e.g. query latency) for a given setting that the
  user can expect? Alternate phrasing: what can we expect in realistic
  workloads that do not saturate the service?

From table below, the answer can be read off from the appropriate
row.

The inclusion of target QPS vs attained QPS is to answer the third
question. For example, if a user does not hit the maximum QPS possible
from a given DNS server pod, then what are the latencies that they
should expect? Latency increases with load and if a user's
applications do not saturate the service, they will attain better
latencies.

## Table fields

* cached - Whether or not the dnsmasq cache was used
* kubedns_cpu - Resource limit for kubedns
* dnsmasq_cpu - Resource limit for kubedns
* query_type - Type of DNS query
* target QPS - Queries per second (QPS) target for
  dnsperf. `unlimited` means run the DNS system to saturation.
* attained QPS - Average QPS we got on the run
* avg, max latency - Average, maximum query latency
* 50, .. %tile - Latency percentiles (ms)

""")
out.write('|'.join(headings) + '\n')
out.write('|'.join(['----'] * len(headings)) + '\n')

for cache in dnsmasq_cache:
    for kc in kubedns_cpu:
        for dc in dnsmasq_cpu:
            for qt in query_type:
                for mq in max_qps:
                    values = []
                    cursor.execute(
                        'select qps, avg_latency, max_latency from runs where ' +
                        ' dnsmasq_cache = ? '
                        ' and kubedns_cpu = ? '
                        ' and dnsmasq_cpu = ? '
                        ' and query_type = ? '
                        ' and max_qps = ?',
                        (cache, kc, dc, qt, mq))

                    values.extend([
                        'Y' if (int(cache) > 0) else 'N',
                        kc if kc else 'unlimited',
                        dc if dc else 'unlimited',
                        qt,
                        mq.lstrip('-Q') if mq else '-'])

                    rows = cursor.fetchall()
                    if len(rows) == 0: continue
                    qps, avg_latency, max_latency = rows[0]

                    if not qps: continue

                    values.extend([
                        int(qps) if qps else 'invalid',
                        round(avg_latency*1000,1) if avg_latency else 'invalid',
                        round(1000*max_latency,1) if avg_latency else 'invalid'])

                    cursor.execute(
                        'select rtt_ms, rtt_ms_count from histograms where ' +
                        ' dnsmasq_cache = ? '
                        ' and kubedns_cpu = ? '
                        ' and dnsmasq_cpu = ? '
                        ' and query_type = ? '
                        ' and max_qps = ? '
                        ' order by rtt_ms',
                        (cache, kc, dc, qt, mq))

                    data = []
                    for rtt, count in cursor.fetchall():
                        data += ([rtt]*int(count))

                    values.extend(
                        [round(numpy.percentile(data, x),1) for x in [50, 95, 99, 99.5]])

                    out.write('|'.join([str(x) for x in values]) + '\n')

print out.getvalue()
