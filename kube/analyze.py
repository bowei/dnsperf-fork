#!/usr/bin/env python

import argparse
import re
import sqlite3
import sys
import logging

_log = logging.getLogger()

class App(object):
  def __init__(self):
    self.args = None
    self.db = None
    self.params = None
    self.results = None
    self.histogram = []

  def parse_args(self):
    parser = argparse.ArgumentParser(
        description="""
        Parses the output of the measurement runs and inserts the data
        into a database for analysis.
        """)
    parser.add_argument(
        '--input', type=str, required=True,
        help='Input log file.')
    parser.add_argument(
        '--db', type=str, default='dnsperf.db',
        help='Database to add the data to. This is a sqlite3 database.')
    parser.add_argument(
        '--update', action='store_true',
        help='If set only add data points if the run does not already ' +
             'exist in the DB')

    self.args = parser.parse_args()

  def ensure_db(self):
    self.db = sqlite3.connect(self.args.db)
    c = self.db.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS runs (
    run_id,
    dnsperf_queries,
    kubedns_cpu,
    dnsmasq_cpu,
    dnsmasq_cache,
    max_qps,
    query_type,
    queries_sent real,
    queries_completed real,
    queries_lost real,
    run_time real,
    qps real,
    avg_latency real,
    min_latency real,
    max_latency real,
    stddev_latency real,

    primary key (
      run_id,
      dnsperf_queries,
      kubedns_cpu,
      dnsmasq_cpu,
      dnsmasq_cache,
      max_qps,
      query_type))''')

    c.execute('''CREATE TABLE IF NOT EXISTS histograms (
    run_id,
    dnsperf_queries,
    kubedns_cpu,
    dnsmasq_cpu,
    dnsmasq_cache,
    max_qps,
    query_type,
    rtt_ms real,
    rtt_ms_count real)''')

    self.db.commit()

  def parse_file(self):
    lines = open(self.args.input, 'r').readlines()
    lines = [x.strip() for x in lines]
    self.parse_params(lines)
    self.parse_results(lines)
    self.parse_histogram(lines)

  def parse_params(self, lines):
    params = {}

    match = re.match('### (?:run_id |date: )(.*)', lines[0])
    params['run_id'] = match.group(1)

    settings=[l for l in lines if re.match('^### set .*', l)]
    for line in settings:
      match = re.match('^### set (.*)_opt.*=(.*)', line)
      params[match.group(1)] = match.group(2)

      self.params = params

  RESULT_RE = {
      'queries_sent': re.compile(r'\s*Queries sent:\s*(\d+)'),
      'queries_completed': re.compile(r'\s*Queries completed:\s*(\d+).*'),
      'queries_lost': re.compile(r'\s*Queries lost:\s*(\d+).*'),
      'run_time': re.compile(r'\s*Run time \(s\):\s*([0-9.]+)'),
      'qps': re.compile(r'\s*Queries per second:\s*([0-9.]+)'),

      'avg_latency': re.compile(r'\s*Average Latency \(s\):\s*([0-9.]+).*'),
      'min_latency': re.compile(r'\s*Average Latency \(s\):.*min ([0-9.]+).*'),
      'max_latency': re.compile(r'\s*Average Latency \(s\):.*max ([0-9.]+).*'),
      'stddev_latency': re.compile(r'\s*Latency StdDev \(s\):\s*([0-9.]+)'),
  }

  def parse_results(self, lines):
    results = {}
    for line in lines:
      for key, regex in self.RESULT_RE.items():
        match = regex.match(line)
        if not match: continue
        results[key] = float(match.group(1))
    self.results = results

  def parse_histogram(self, lines):
    lines = [x for x in lines if re.match('^#histogram .*', x)]
    for line in lines:
      match = re.match(r'^#histogram\s+(\d+) (\d+)', line)
      rtt, count = map(float, match.groups())
      self.histogram.append((rtt, count))

  def insert_data(self):
    c = self.db.cursor()

    pkey = ['run_id', 'dnsperf_queries', 'kubedns_cpu', 'dnsmasq_cpu', 'dnsmasq_cache',
            'max_qps', 'query_type']

    sql = 'SELECT count(*) FROM runs WHERE ' + ' AND '.join(['{} = ?'.format(x) for x in pkey])
    c.execute(sql, [self.params[x] for x in pkey])
    rows = c.fetchall()
    if self.args.update and int(rows[0][0]) > 0:
      _log.info('Skipping run "%s" as it is already in the database',
                self.params['run_id'])
      return

    merged = dict(self.params.items() + self.results.items())
    columns = ','.join(merged.keys())
    qs = ','.join(['?'] * len(merged))
    values = merged.values()

    stmt = 'INSERT INTO runs (' + columns + ') VALUES (' + qs +')'
    c.execute(stmt, values)

    for rtt_ms, count in self.histogram:
      data = dict(self.params)
      data['rtt_ms'] = rtt_ms
      data['rtt_ms_count'] = count

      columns = ','.join(data.keys())
      qs = ','.join(['?'] * len(data))
      stmt = 'INSERT INTO histograms (' + columns + ') VALUES (' + qs + ')'
      c.execute(stmt, data.values())

    self.db.commit()
    _log.info('Processed "%s"', self.params['run_id'])

  def main(self):
    logging.basicConfig(level=logging.INFO)

    args = self.parse_args()
    self.ensure_db()
    self.parse_file()
    self.insert_data()

app = App()
app.main()
