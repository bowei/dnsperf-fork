# -*- coding: utf-8 -*-
import sqlite3
import numpy
import StringIO

conn = sqlite3.connect('dnsperf.db')
cursor = conn.cursor()

dnsmasq_cache = ['0', '10000']
kubedns_cpu = ['200m', '250m']
dnsmasq_cpu = ['100m', '200m', '250m']
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

This directory contains scripts used to run a dns performance test against a
kubernetes cluster.

See ./run-dnsperf.sh --help for details.

# Raw data

This is the raw data for kube-dns performance.

* cached - whether or not the dnsmasq cache was used
* kubedns_cpu - resource limit for kubedns
* dnsmasq_cpu - resource limit for kubedns
* query_type - type of DNS query
* target QPS - queries per second (QPS) target for with dnsperf
* attained QPS - average QPS we got on the run
* avg, max latency - average, maximum query latency
* 50, .. %tile - latency percentiles

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

                    values.extend(['Y' if (int(cache) > 0) else 'N', kc, dc, qt, mq.lstrip('-Q') if mq else '-'])

                    rows = cursor.fetchall()
                    if len(rows) == 0: continue
                    qps, avg_latency, max_latency = rows[0]

                    values.extend([int(qps), round(avg_latency*1000,1), round(1000*max_latency,1)])

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
