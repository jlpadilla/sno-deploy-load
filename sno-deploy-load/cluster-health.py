#!/usr/bin/env python3
#
# Check if cluster is healthy/stable
# * Check if clusterversion is available
# * Check if all clusteroperators available
# * Check if all nodes are ready
# * Check if all machineconfigpools updated
# * Check for etcd leader elections in the last hour
#
#  Copyright 2022 Red Hat
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import argparse
import base64
from datetime import datetime
import json
from utils.command import command
import logging
import numpy as np
import requests
import sys
import time


logging.basicConfig(level=logging.INFO, format="%(asctime)s : %(levelname)s : %(threadName)s : %(message)s")
logger = logging.getLogger("cluster-health")
logging.Formatter.converter = time.gmtime


# TODO: Future Enhancements:
# * parameter to increase length of time to check for etcd leader elections
# * Check if nodes flapped? (in last hour or larger period time)
# * Check critical ocp pods (Ex kube-apiserver) for restarts in last hour (or timeframe)
# * Abstract the prometheus query logic such that more queries can be completed easily
# * Create a test namespace, deployment, pod, service, route and check route for http 200, then tear down


def get_version(kubeconfig):
  logger.info("Getting version")
  version = {}
  oc_cmd = ["oc", "--kubeconfig", kubeconfig, "version", "-o", "json"]
  rc, output = command(oc_cmd, False, no_log=True)
  if rc != 0:
    logger.error("cluster-health, oc version rc: {}".format(rc))
    sys.exit(1)
  version_data = json.loads(output)
  logger.debug("Version is {}".format(version_data["openshiftVersion"]))
  version["major"] = int(version_data["openshiftVersion"].split(".")[0])
  version["minor"] = int(version_data["openshiftVersion"].split(".")[1])
  version["patch"] = int(version_data["openshiftVersion"].split(".")[2])
  return version


def check_clusterversion(kubeconfig, force):
  logger.info("Checking clusterversion")
  success = True
  oc_cmd = ["oc", "--kubeconfig", kubeconfig, "get", "clusterversion", "version", "-o", "json"]
  rc, output = command(oc_cmd, False, no_log=True)
  if rc != 0:
    logger.error("cluster-health, oc get clusterversion version rc: {}".format(rc))
    sys.exit(1)
  cv_data = json.loads(output)

  cv_available = [con for con in cv_data["status"]["conditions"] if con["type"] == "Available"][0]["status"]
  cv_failing = [con for con in cv_data["status"]["conditions"] if con["type"] == "Failing"][0]["status"]
  cv_progressing = [con for con in cv_data["status"]["conditions"] if con["type"] == "Progressing"][0]["status"]

  if cv_available == "True":
    logger.debug("Clusterversion is Available")
  else:
    logger.error("Clusterversion is not Available")
    success = False
    if not force:
      sys.exit(1)

  if cv_failing == "True":
    logger.error("Clusterversion is Failing")
    success = False
    if not force:
      sys.exit(1)
  else:
    logger.debug("Clusterversion is not Failing")

  if cv_progressing == "True":
    logger.error("Clusterversion is Progressing")
    success = False
    if not force:
      sys.exit(1)
  else:
    logger.debug("Clusterversion is not Progressing")
  return success


def check_clusteroperators(kubeconfig, force):
  logger.info("Checking clusteroperators")
  success = True
  oc_cmd = ["oc", "--kubeconfig", kubeconfig, "get", "clusteroperators", "-o", "json"]
  rc, output = command(oc_cmd, False, no_log=True)
  if rc != 0:
    logger.error("cluster-health, oc get clusteroperators rc: {}".format(rc))
    sys.exit(1)
  co_data = json.loads(output)

  for operator in co_data["items"]:
    operator_name = operator["metadata"]["name"]
    co_available = [con for con in operator["status"]["conditions"] if con["type"] == "Available"][0]["status"]
    co_degraded = [con for con in operator["status"]["conditions"] if con["type"] == "Degraded"][0]["status"]
    co_progressing = [con for con in operator["status"]["conditions"] if con["type"] == "Progressing"][0]["status"]
    logger.debug("Operator: {}, Available: {}, Progressing: {}, Degraded: {}".format(
        operator_name, co_available, co_progressing, co_degraded))
    if co_available != "True":
      logger.error("Clusteroperator {} is not Available".format(operator_name))
      success = False
      if not force:
        sys.exit(1)

    if co_degraded == "True":
      logger.error("Clusteroperator {} is Degraded".format(operator_name))
      success = False
      if not force:
        sys.exit(1)

    if co_progressing == "True":
      logger.error("Clusteroperator {} is Progressing".format(operator_name))
      success = False
      if not force:
        sys.exit(1)
  return success


def check_nodes(kubeconfig, force):
  logger.info("Checking nodes")
  success = True
  oc_cmd = ["oc", "--kubeconfig", kubeconfig, "get", "nodes", "-o", "json"]
  rc, output = command(oc_cmd, False, no_log=True)
  if rc != 0:
    logger.error("cluster-health, oc get nodes rc: {}".format(rc))
    sys.exit(1)
  no_data = json.loads(output)

  for node in no_data["items"]:
    node_name = node["metadata"]["name"]
    no_ready = [con for con in node["status"]["conditions"] if con["type"] == "Ready"][0]["status"]
    no_memory = [con for con in node["status"]["conditions"] if con["type"] == "MemoryPressure"][0]["status"]
    no_disk = [con for con in node["status"]["conditions"] if con["type"] == "DiskPressure"][0]["status"]
    no_pid = [con for con in node["status"]["conditions"] if con["type"] == "PIDPressure"][0]["status"]
    logger.debug("Node: {}, Ready: {}, MemoryPressure: {}, DiskPressure: {}, PIDPressure: {}".format(
        node_name, no_ready, no_memory, no_disk, no_pid))
    if no_ready != "True":
      logger.error("Node {} is not Ready".format(node_name))
      success = False
      if not force:
        sys.exit(1)

    if no_memory == "True":
      logger.error("Node {} is has MemoryPressure".format(node_name))
      success = False
      if not force:
        sys.exit(1)

    if no_disk == "True":
      logger.error("Node {} is has DiskPressure".format(node_name))
      success = False
      if not force:
        sys.exit(1)

    if no_pid == "True":
      logger.error("Node {} is has PIDPressure".format(node_name))
      success = False
      if not force:
        sys.exit(1)
  return success


def check_machineconfigpools(kubeconfig, force):
  logger.info("Checking machineconfigpools")
  success = True
  oc_cmd = ["oc", "--kubeconfig", kubeconfig, "get", "machineconfigpools", "-o", "json"]
  rc, output = command(oc_cmd, False, no_log=True)
  if rc != 0:
    logger.error("cluster-health, oc get machineconfigpools rc: {}".format(rc))
    sys.exit(1)
  mcp_data = json.loads(output)

  for mcp in mcp_data['items']:
    # logger.info("MCP: {}".format(mcp))
    mcp_name = mcp["metadata"]["name"]
    mcp_updated = [con for con in mcp["status"]["conditions"] if con["type"] == "Updated"][0]["status"]
    mcp_updating = [con for con in mcp["status"]["conditions"] if con["type"] == "Updating"][0]["status"]
    mcp_nodedegraded = [con for con in mcp["status"]["conditions"] if con["type"] == "NodeDegraded"][0]["status"]
    mcp_degraded = [con for con in mcp["status"]["conditions"] if con["type"] == "Degraded"][0]["status"]
    logger.debug("MCP: {}, Updated: {}, Updating: {}, NodeDegraded: {}, Degraded: {}".format(
        mcp_name, mcp_updated, mcp_updating, mcp_nodedegraded, mcp_degraded))

    if mcp_updated != "True":
      logger.error("MCP {} is not Updated".format(mcp_name))
      success = False
      if not force:
        sys.exit(1)

    if mcp_updating == "True":
      logger.error("MCP {} is Updating".format(mcp_name))
      success = False
      if not force:
        sys.exit(1)

    if mcp_nodedegraded == "True":
      logger.error("MCP {} is NodeDegraded".format(mcp_name))
      success = False
      if not force:
        sys.exit(1)

    if mcp_degraded == "True":
      logger.error("MCP {} is Degraded".format(mcp_name))
      success = False
      if not force:
        sys.exit(1)

  return success


def check_etcd_leader_elections(kubeconfig, force, version):
  logger.info("Checking for etcd leader elections")
  success = True
  prom_route = ""
  prom_token_name = ""
  prom_token_data = ""

  oc_cmd = ["oc", "--kubeconfig", kubeconfig, "get", "route", "thanos-querier", "-n", "openshift-monitoring", "-o", "jsonpath={.spec.host}"]
  rc, output = command(oc_cmd, False, no_log=True)
  if rc != 0:
    logger.error("cluster-health, oc get route thanos-querier -n openshift-monitoring rc: {}".format(rc))
    sys.exit(1)

  if "thanos-querier" in output:
    prom_route = "https://{}".format(output)
  else:
    logger.error("Failed to find route for thanos-querier")
    sys.exit(1)

  logger.info("Route to Query: {}".format(prom_route))

  prom_token_data = ""
  if version["major"] == 4 and version["minor"] > 10:
    # 4.11 requires us to create the token instead of find it in a secret
    oc_cmd = ["oc", "--kubeconfig", kubeconfig, "create", "token", "prometheus-k8s", "-n", "openshift-monitoring"]
    rc, output = command(oc_cmd, False, no_log=True)
    if rc != 0:
      logger.error("cluster-health, oc create token prometheus-k8s -n openshift-monitoring rc: {}".format(rc))
      sys.exit(1)
    prom_token_data = output
  elif version["major"] == 4 and version["minor"] <= 10:
    # 4.10 and below the token is located in a secret
    oc_cmd = ["oc", "--kubeconfig", kubeconfig, "get", "serviceaccount", "prometheus-k8s", "-n", "openshift-monitoring", "-o", "json"]
    rc, output = command(oc_cmd, False, no_log=True)
    if rc != 0:
      logger.error("cluster-health, oc get serviceaccount prometheus-k8s -n openshift-monitoring rc: {}".format(rc))
      sys.exit(1)
    prom_sa_data = json.loads(output)

    for secret_name in prom_sa_data["secrets"]:
      if "token" in secret_name["name"]:
        prom_token_name = secret_name["name"]
        break

    if prom_token_name == "":
      logger.error("Unable to identify prometheus token name")
      sys.exit(1)

    oc_cmd = ["oc", "--kubeconfig", kubeconfig, "get", "secret", prom_token_name, "-n", "openshift-monitoring", "-o", "json"]
    rc, output = command(oc_cmd, False, no_log=True)
    if rc != 0:
      logger.error("cluster-health, oc get secret {} -n openshift-monitoring rc: {}".format(prom_token_name, rc))
      sys.exit(1)
    prom_secret_data = json.loads(output)

    prom_token_data = (base64.b64decode(prom_secret_data["data"]["token"])).decode("utf-8")
    if prom_token_data == "":
      logger.error("Unable to identify prometheus token name")
      sys.exit(1)

  query = "increase(etcd_server_leader_changes_seen_total[1h])"
  query_endpoint = "{}/api/v1/query?query={}".format(prom_route, query)
  headers = {"Authorization": "Bearer {}".format(prom_token_data)}
  query_data = requests.post(query_endpoint, headers=headers, verify=False).json()

  logger.debug("Length of returned data: {}".format(len(query_data["data"]["result"])))

  for result in query_data["data"]["result"]:
    if float(result["value"][1]) > 0:
      logger.error("Pod: {}, Instance: {}, Result: {}".format(result["metric"]["pod"],result["metric"]["instance"], float(result["value"][1])))
      logger.error("etcd encountered leader election(s) in the last hour")
      success = False
      if not force:
        sys.exit(1)
  return success


def main():
  start_time = time.time()
  healthy = 0

  parser = argparse.ArgumentParser(
      description="Check that a cluster is healthy and stable",
      prog="cluster-health.py", formatter_class=argparse.ArgumentDefaultsHelpFormatter)

  parser.add_argument("-k", "--kubeconfig", type=str, default="/root/bm/kubeconfig",
                      help="Changes which kubeconfig to connect to a cluster")
  parser.add_argument("-f", "--force", action="store_true", default=False,
                      help="Do not exit on first failed check")

  parser.add_argument("--skip-clusterversion", action="store_true", default=False,
                      help="Skip checking clusterversion object")
  parser.add_argument("--skip-clusteroperator", action="store_true", default=False,
                      help="Skip checking clusteroperator objects")
  parser.add_argument("--skip-node", action="store_true", default=False,
                      help="Skip checking node objects")
  parser.add_argument("--skip-machineconfigpool", action="store_true", default=False,
                      help="Skip checking machineconfigpool objects")
  parser.add_argument("--skip-etcd-election", action="store_true", default=False,
                      help="Skip checking for etcd leader elections")


  parser.add_argument("-d", "--debug", action="store_true", default=False, help="Set log level debug")
  cliargs = parser.parse_args()

  if cliargs.debug:
    logger.setLevel(logging.DEBUG)

  version = get_version(cliargs.kubeconfig)
  logger.info("oc version reports cluster is {}.{}.{}".format(version["major"], version["minor"], version["patch"]))

  logger.info("Checking cluster")
  ts = datetime.now().strftime("%Y%m%d-%H%M%S")

  if not cliargs.skip_clusterversion:
    if check_clusterversion(cliargs.kubeconfig, cliargs.force):
      logger.info("Clusterversion is Available and not failing")
    else:
      healthy += 1
  else:
    logger.info("Skip checking clusterversion")

  if not cliargs.skip_clusteroperator:
    if check_clusteroperators(cliargs.kubeconfig, cliargs.force):
      logger.info("All clusteroperators are Available")
    else:
      healthy += 1
  else:
    logger.info("Skip checking clusteroperators")

  if not cliargs.skip_node:
    if check_nodes(cliargs.kubeconfig, cliargs.force):
      logger.info("All nodes are Ready")
    else:
      healthy += 1
  else:
    logger.info("Skip checking node readiness")

  if not cliargs.skip_machineconfigpool:
    if check_machineconfigpools(cliargs.kubeconfig, cliargs.force):
      logger.info("All machineconfigpool are Updated")
    else:
      healthy += 1
  else:
    logger.info("Skip checking machineconfigpool")

  if not cliargs.skip_etcd_election:
    if check_etcd_leader_elections(cliargs.kubeconfig, cliargs.force, version):
      logger.info("No detected etcd leader elections in the last hour")
    else:
      healthy += 1
  else:
    logger.info("Skip checking for etcd leader elections")

  if healthy > 0:
    logger.warning("Cluster failed one or more checks")
  else:
    logger.info("Cluster appears healthy!!!")
  end_time = time.time()
  logger.info("Took {}s".format(round(end_time - start_time, 1)))
  return healthy

if __name__ == "__main__":
  sys.exit(main())
