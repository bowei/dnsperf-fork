#!/usr/bin/env python
import argparse
import json
import sys

def parse_args():
  parser = argparse.ArgumentParser()
  parser.add_argument('--input', type=str)
  parser.add_argument('--dnsmasq_cache', type=str)
  parser.add_argument('--dnsmasq_cpu', type=str)
  parser.add_argument('--kubedns_cpu', type=str)

  return parser.parse_args()

def fix_resources(container, cpu):
  if cpu:
    container['resources']['limits'] = {'cpu': cpu}
    container['resources']['requests'] = {'cpu': cpu}
  else:
    container['resources']['limits'] = {}
    container['resources']['requests'] = {'cpu': '100m'}

def fix_dnsmasq(container_spec):
  cmd_args = container_spec['args']
  cmd_args = filter(lambda x: not x.startswith('--cache-size='), cmd_args)
  cmd_args.append('--cache-size={}'.format(args.dnsmasq_cache))
  container_spec['args'] = cmd_args

args = parse_args()
fh = open(args.input, 'r')
rc = json.loads(fh.read())

containers = rc['spec']['template']['spec']['containers']
for container in containers:
  if container['name'] == 'kubedns':
    fix_resources(container, args.kubedns_cpu)
  elif container['name'] == 'dnsmasq':
    fix_resources(container, args.dnsmasq_cpu)
    fix_dnsmasq(container)

print json.dumps(rc, indent=2)
