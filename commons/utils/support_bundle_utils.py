#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2020 Seagate Technology LLC and/or its Affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# For any questions about this software or licensing,
# please email opensource@seagate.com or cortx-questions@seagate.com.

"""
Module to maintain support bundle utils
"""

import os
import logging
import time
from commons.helpers.node_helper import Node
from commons.utils import config_utils
from config import CMN_CFG

# Global Constants
LOGGER = logging.getLogger(__name__)


def create_support_bundle_individual_cmd(node, username, password, remote_dir, local_dir, component="all"):
    """
    Collect support bundles from various components
    :param node: Node hostname on which support bundle to be generated
    :param username: username of the node
    :param password: password of the node
    :param component: component to create support bundle, default creates for all components
    :param remote_dir: Directory on node where support bundles will be collected
    :param local_dir: Local directory where support bundles will be copied
    :return: True/False and local sb path
    """
    node_obj = Node(hostname=node, username=username, password=password)
    if node_obj.path_exists(remote_dir):
        node_obj.remove_dir(remote_dir)
    node_obj.create_dir_sftp(remote_dir)
    sb_cmds = {"sspl": "/usr/bin/sspl_bundle_generate support_bundle {}",
               "s3": "sh /opt/seagate/cortx/s3/scripts/s3_bundle_generate.sh support_bundle {}",
               "manifest": "/usr/bin/manifest_support_bundle support_bundle {}",
               "hare": "/opt/seagate/cortx/hare/bin/hare_setup support_bundle support_bundle {}",
               "provisioner": "/opt/seagate/cortx/provisioner/cli/provisioner-bundler support_bundle {}",
               "cortx": "cortx support_bundle create support_bundle {}",
               "csm": "cortxcli csm_bundle_generate csm support_bundle {}"
               }

    if component == "all":
        for comp, cmd in sb_cmds.items():
            LOGGER.info("Generating support bundle for %s component on node %s", comp, node)
            node_obj.execute_cmd(cmd.format(remote_dir))
    elif component in sb_cmds:
        LOGGER.info("Generating support bundle for %s component on node %s", component, node)
        node_obj.execute_cmd(sb_cmds[component].format(remote_dir))
    else:
        return False, "Invalid Component"

    LOGGER.info("Copying generated support bundle to local")
    sb_tar_file = "".join([os.path.basename(remote_dir), ".tar"])
    remote_sb_path = os.path.join(os.path.dirname(remote_dir), sb_tar_file)
    local_sb_path = os.path.join(local_dir, sb_tar_file)
    tar_sb_cmd = "tar -cvf {} {}".format(remote_sb_path, remote_dir)
    node_obj.execute_cmd(tar_sb_cmd)
    LOGGER.debug("Copying %s to %s", remote_sb_path, local_sb_path)
    node_obj.copy_file_to_local(remote_sb_path, local_sb_path)

    return True, local_sb_path


def create_support_bundle_single_cmd(remote_dir, local_dir, bundle_name):
    """
    Collect support bundles from various components using single support bundle cmd
    :param remote_dir: Directory on node where support bundles will be collected
    :param local_dir: Local directory where support bundles will be copied
    :param bundle_name: Name of bundle
    :return: True/False and local sb path
    """
    primary_node_obj = Node(
        hostname=CMN_CFG["nodes"][0]["hostname"],
        username=CMN_CFG["nodes"][0]["username"],
        password=CMN_CFG["nodes"][0]["password"])
    shared_path = "glusterfs://{}".format(remote_dir)
    remote_dir = os.path.join(remote_dir, "support_bundle")
    if primary_node_obj.path_exists(remote_dir):
        primary_node_obj.remove_dir(remote_dir)
    primary_node_obj.create_dir_sftp(remote_dir)

    LOGGER.info("Updating shared path for support bundle %s", shared_path)
    cortx_conf = "/etc/cortx/cortx.conf"
    temp_conf = os.path.join(os.getcwd(), "cortx.conf")
    primary_node_obj.copy_file_to_local(cortx_conf, temp_conf)
    conf = config_utils.read_content_json(temp_conf)
    conf["support"]["shared_path"] = shared_path
    config_utils.create_content_json(temp_conf, conf)
    for node in CMN_CFG["nodes"]:
        node_obj = Node(node["hostname"], node["username"], node["password"])
        node_obj.copy_file_to_remote(temp_conf, cortx_conf)

    LOGGER.info("Starting support bundle creation")
    primary_node_obj.execute_cmd(
        "support_bundle generate {}".format(bundle_name))
    start_time = time.time()
    timeout = 2700
    bundle_id = primary_node_obj.list_dir(remote_dir)[0]
    LOGGER.info(bundle_id)
    bundle_dir = os.path.join(remote_dir, bundle_id)
    success_msg = "Support bundle generation completed."
    while timeout > time.time() - start_time:
        time.sleep(180)
        LOGGER.info("Checking Support Bundle status")
        status = primary_node_obj.execute_cmd(
            "support_bundle get_status -b {}".format(bundle_id))
        if str(status).count(success_msg) == len(CMN_CFG["nodes"]):
            LOGGER.info(success_msg)
            LOGGER.info("Archiving and copying Support bundle from server")
            sb_tar_file = "".join([bundle_id, ".tar"])
            remote_sb_path = os.path.join(remote_dir, sb_tar_file)
            local_sb_path = os.path.join(local_dir, sb_tar_file)
            tar_sb_cmd = "tar -cvf {} {}".format(remote_sb_path, bundle_dir)
            primary_node_obj.execute_cmd(tar_sb_cmd)
            primary_node_obj.copy_file_to_local(remote_sb_path, local_sb_path)
            break
    else:
        LOGGER.error("Timeout while generating support bundle")
        return False, "Timeout while generating support bundle"

    return True, local_sb_path