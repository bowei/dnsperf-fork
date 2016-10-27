#!/bin/bash

set -e

devnull=/dev/null
run_id=`date +%s`

usage() {
  cat <<END
run-dnsperf.sh

OVERVIEW

Run a performance evaluation of the kube-dns subsystem. This test
assumes that your kubectl and cluster is functional and contains at
least two minion nodes.

This test does the following:

* Selects one node as the server, one node as the client
* Scales kube-dns to 1 pod and pins kube-dns to run only on the
  server.
* Launches a pod on the client node for running dnsperf.

The perf test will then cycle through test parameters (see below) and
output the results to RUN_ID/*.out. The latest run is accessible from
the 'latest' symlink.

Analyze the test results with analyze.py:

  $ ls latest/* | xargs -n1 ./analyze.py --input

PARAMETERS

  dnsperf_queries_opt   number of queries to issue 
  kubedns_cpu_opt       kubedns cpu limit
  dnsmasq_cpu_opt       dnsmasq cpu limit
  dnsmasq_cache_opt     dnsmasq cache size
  max_qps_opt           maximum qps to send from dnsperf
  query_type_opt        type of query (see queries/*.txt)

OPTIONS
  -h           This help message.
  -f FILENAME  Rerun a single performance run given its output file. 
               Look at the log file for details.
END
}

parse_args() {
  local opt_file=

  while [ ! -z "$1" ]; do
    case "$1" in
      -f) shift; opt_file="$1"; shift;;
      -h|--h|-help|--help) usage; exit 0;;
      *) echo "Invalid option: $1"; exit 1;;
    esac
  done

  echo "### run_id ${run_id}"
  
  if [ ! -z "${opt_file}" ]; then
    if [ ! -r "${opt_file}" ]; then
      echo "### Cannot read file: ${opt_file}"
      exit 1
    fi

    echo "### Loading opts from file ${opt_file}"
    local tmpfile="/tmp/run-dnsperf.$$.settings"
    grep '### set ' "${opt_file}" | sed 's/^### set /export /' > "${tmpfile}"
    . "${tmpfile}"
  fi

  # See usage doc above.
  dnsperf_queries_opt=${dnsperf_queries_opt:-10000}
  kubedns_cpu_opt=${kubedns_cpu_opt:-100m 200m 250m 500m -}
  dnsmasq_cpu_opt=${dnsmasq_cpu_opt:-100m 200m 250m 500m -}
  dnsmasq_cache_opt=${dnsmasq_cache_opt:-0 10000}
  max_qps_opt=${max_qps_opt:--Q500 -Q1000 -Q2000 -Q3000 -}
  query_type_opt=${query_type_opt:-nx-domain outside pod-ip service}
}

print_opt() {
  for v in dnsperf_queries_opt kubedns_cpu_opt dnsmasq_cpu_opt max_qps_opt query_type_opt; do
    local t="${v}=\${$v}"
    echo -n "### "
    eval echo $t
  done
}

label_nodes() {
  echo "### Removing existing labels"
  kubectl label nodes --all dnsperf- >"${devnull}" 2>"${devnull}"
  local nodes=`kubectl get nodes | grep 'minion' | awk '{print($1)}' | head -n 2`
  label_nodes_ ${nodes}
}

label_nodes_() {
  local client="$1"
  local server="$2"

  kubectl label node "${client}" dnsperf=client >"${devnull}" 2>"${devnull}"
  kubectl label node "${server}" dnsperf=server >"${devnull}" 2>"${devnull}"

  echo "### ${client} is the client node (dnsperf=client)"
  echo "### ${server} is the server node (dnsperf=server)"
}

restrict_dns() {
  # restrict dns server to only start up on the server node
  kubectl patch --namespace kube-system rc/kube-dns-v20 \
    -p '{"spec":{"template":{"spec":{"nodeSelector":{"dnsperf":"server"}}}}}' \
    >"${devnull}" 2>"${devnull}"
}

restart_dns() {
  kubectl patch --namespace kube-system rc/kube-dns-v20 \
    -p '{"spec":{"replicas":0}}' \
    >"${devnull}" 2>"${devnull}"

  echo -n '### Waiting for DNS to terminate'
  while kubectl get pods --namespace kube-system --show-all \
      | grep -q kube-dns; do
    echo -n '.'
    sleep 1
  done
  echo
  
  kubectl patch --namespace kube-system rc/kube-dns-v20 \
    -p '{"spec":{"replicas":1}}' \
    >"${devnull}" 2>"${devnull}"

  echo -n '### Waiting for DNS to start'
  while ! kubectl get pods --namespace kube-system --show-all \
      | grep -q 'kube-dns.*3/3.*Running'; do
    echo -n '.'
    sleep 1
  done
  echo
}

reset_client_pod() {
  if kubectl get pod dnsperf-client >"${devnull}" 2>"${devnull}"; then
    kubectl delete pod dnsperf-client || true
    
    echo -n "### Waiting for dnsperf-client to be deleted"
    while kubectl get pod dnsperf-client | grep -q Terminating >"${devnull}" 2>"${devnull}"; do
      echo -n .
      sleep 1
    done
    echo
  fi
  
  # Creates a pod on the client node to be a target for our exec's of
  # dnsperf.
  cat <<END | kubectl create -f - >"${devnull}" 2>"${devnull}"
apiVersion: v1
kind: Pod
metadata:
  name: dnsperf-client
spec:
  nodeSelector:
    dnsperf: client
  containers:
  - name: dnsperf
    image: gcr.io/bowei-gke-dev/dnsperf:1.0
    imagePullPolicy: Always
    command: ["sleep"]
    args: ["777777"]
END
}

setup_dns() {
  local tmp1=/tmp/rc_kube_dns_v20
  local tmp2=/tmp/rc_kube_dns_v20.new
  
  local kubedns_cpu="$1"
  local dnsmasq_cpu="$2"
  local dnsmasq_cache="$3"

  kubectl get --namespace kube-system rc/kube-dns-v20 -o json \
    > "${tmp1}" 2>"${devnull}"
  
  python setup_dns.py \
    --input "${tmp1}" \
    --kubedns_cpu="$kubedns_cpu" \
    --dnsmasq_cpu="$dnsmasq_cpu" \
    --dnsmasq_cache="$dnsmasq_cache" \
    > "${tmp2}"
  
  kubectl replace -f "${tmp2}" \
    >"${devnull}" 2>"${devnull}"
}

run_experiment() {
  local results_dir=`date +%s`
  mkdir -p "${results_dir}"
  ln -Tsf "${results_dir}" latest
  
  for kubedns_cpu in ${kubedns_cpu_opt}; do
    for dnsmasq_cpu in ${dnsmasq_cpu_opt}; do
      for dnsmasq_cache in ${dnsmasq_cache_opt}; do
        setup_dns "${kubedns_cpu}" "${dnsmasq_cpu}" "${dnsmasq_cache}"
        restart_dns

        for max_qps in ${max_qps_opt}; do
          for query_type in ${query_type_opt}; do

            if [ "${kubedns_cpu}" = '-' ]; then kubedns_cpu=''; fi
            if [ "${dnsmasq_cpu}" = '-' ]; then dnsmasq_cpu=''; fi
            if [ "${max_qps}" = '-' ]; then max_qps=''; fi

            local outfile
            outfile="${results_dir}/dnsperf_${kubedns_cpu}_${dnsmasq_cpu}_${dnsmasq_cache}_${max_qps}_${query_type}.out"
            
            echo "### run_id ${run_id}" >> "${outfile}"
            echo -n "### date: " >>"${outfile}"
            date >> "${outfile}"

            echo "### set dnsperf_queries_opt=${dnsperf_queries_opt}" >> "${outfile}"
            echo "### set kubedns_cpu_opt=${kubedns_cpu}" >> "${outfile}"
            echo "### set dnsmasq_cpu_opt=${dnsmasq_cpu}" >> "${outfile}"
            echo "### set dnsmasq_cache_opt=${dnsmasq_cache}" >> "${outfile}"
            echo "### set max_qps_opt=${max_qps}" >> "${outfile}"
            echo "### set query_type_opt=${query_type}" >> "${outfile}"

            local cmd
            cmd="/dnsperf -d /queries/${query_type}.txt -n ${dnsperf_queries_opt} -s 10.0.0.10 ${max_qps}"
            
            echo "### cmd: kubectl exec dnsperf-client -- \\" >> "${outfile}"
            echo "###      $cmd" >> "${outfile}"
            echo "###" >> "${outfile}"
            echo "### To rerun this experiment by itself:" >> "${outfile}"
            echo "### ./run-dnsperf.sh -f ${outfile}" >> "${outfile}"
            echo "###" >> "${outfile}"

            kubectl exec dnsperf-client -- $cmd | tee -a "${outfile}"
          done
        done
      done
    done
  done
}

main() {
  parse_args "$@"
  # print_opt
  label_nodes
  restrict_dns
  reset_client_pod
    
  run_experiment
}

main "$@"
