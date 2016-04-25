#    Copyright 2015 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os
import random
import string
import time


from solar.core.log import log
from solar.core.transports.base import SyncTransport
from solar.core.transports.base import RunTransport
from solar.core.transports.base import SolarTransportResult

from pykube.config import KubeConfig
from pykube.http import HTTPClient
import pykube.objects



class Job(pykube.objects.NamespacedAPIObject):

    version = "batch/v1"
    endpoint = "jobs"
    kind = "Job"


def random_string(length=6):
    return ''.join([random.choice(
        string.ascii_lowercase
    ) for _ in xrange(length)])


class K8SJobSyncTransport(SyncTransport):

    _priority = -1  # shouldn't be used automaticaly

    def __init__(self, *args, **kwargs):
        super(K8SJobSyncTransport, self).__init__(*args, **kwargs)
        self.paths = []

    def make_confimap_data(self, resource, path, num=0):
        num_prefix = num * 1000
        files_data = {}
        keys = {}
        i = 0
        for root, dirs, files in os.walk(path):
            local_root = root.replace('/tmp/solar_local/', '')
            # if local_root.startswith('/'):
            #     local_root = local_root[1:]
            for f in files:
                with open(os.path.join(root, f), 'rb') as fd:
                    data = fd.read()
                key = os.path.join(local_root, f)
                files_data['data%d' % (num_prefix + i)] = data
                keys['data%d' % (num_prefix + i)] = key
                i += 1

        return {'keys': keys, 'files_data': files_data}

    def all_keys(self):
        datas = self.configmap_datas
        keys = {}
        for single in datas:
            keys.update(single['keys'])
        return keys

    def make_configmap_obj(self, datas):
        obj = {
            'apiVersion': 'v1',
            'kind': 'ConfigMap',
            'metadata': {'name': self.configmap_name,
                         'namespace': self.configmap_namespace},
            'data': {}
        }
        obj_data = obj['data']
        for data in datas:
            obj_data.update(data['files_data'])
        return obj

    def copy(self, resource, _from, _to, _use_sudo=False):
        self.paths.append((resource, _from, _to))

    def run_all(self):
        api = HTTPClient(KubeConfig.from_file('~/.kube/config'))
        datas = []
        for i, (resource, path, to) in enumerate(self.paths):
            datas.append(self.make_confimap_data(resource, path, i))

        self.data_sufix = random_string(8)
        self.configmap_name = 'configmap' + resource.name + self.data_sufix
        self.configmap_namespace = 'default'
        self.configmap_datas = datas

        obj = self.make_configmap_obj(datas)

        self.configmap_obj = pykube.objects.ConfigMap(api, obj)
        self.configmap_obj.create()
        log.debug("Created ConfigMap: %s", self.configmap_obj.name)
        return


class K8SJobRunTransport(RunTransport):

    def get_volume_items(self, resource):
        # XXX: it's bound to BAT logic, shound't be like that
        keys = resource._bat_transport_sync.all_keys()
        items = []
        for key, path in keys.iteritems():
            items.append({'key': key, 'path': path})
        return items

    def _pod_status(self, pod):
        statuses = pod.obj['status']['containerStatuses']
        for status in statuses:
            rc = status['restartCount']
            log.debug("Checking container status %r for job", status)
            terminated = status.get('terminated')
            if terminated:
                reason = terminated['reason']
                return rc, reason
        return rc, None

    def _clean_job(self, cfg_obj, job_obj):
        log.debug("Cleaning job")
        cfg_obj.delete()
        job_obj.delete()

    def run(self, resource, *args, **kwargs):
        # TODO: clean on exceptions too
        api = HTTPClient(KubeConfig.from_file('~/.kube/config'))
        # handler = resource.db_obj.handler
        command = args
        items = self.get_volume_items(resource)
        sync_transport = resource._bat_transport_sync
        name = resource.name + sync_transport.data_sufix
        job_name = 'job' + name
        # kubernetes api...
        obj = {
            'apiVersion': 'batch/v1',
            'kind': 'Job',
            'metadata': {'name': job_name},
            'spec': {'template':
                     {'metadata': {
                         'name': 'cnts' + name
                         },
                      'spec': {
                          'containers': [
                              {'name': 'cnt' + name,
                               'image': "williamyeh/ansible:alpine3",
                               'command': command,
                               'volumeMounts': [
                                   {'name': 'config-volume',
                                    'mountPath': '/tmp'}
                               ]}
                          ],
                          'volumes': [
                              {'name': 'config-volume',
                               'configMap': {
                                'name': sync_transport.configmap_name,
                                'items': items
                               }}
                          ],
                          'restartPolicy': 'OnFailure'
                      }}}}
        self.job_obj = job_obj = Job(api, obj)
        job_obj.create()
        log.debug("Created JOB: %s", job_obj.name)
        job_status = False
        rc = 0
        while True:
            log.debug("Starting K8S job loop check")
            time.sleep(1)
            job_obj.reload()
            job_status = job_obj.obj['status']
            if job_status.get('active', 0) >= 1:
                log.debug("Job is active")
                # for now assuming that we have only one POD for JOB
                pods = list(pykube.Pod.objects(api).filter(selector='job-name={}'.format(job_name)))
                if pods:
                    pod = pods[0]
                    log.debug("Found pods for job")
                    rc, status = self._pod_status(pod)
                    if rc > 1:
                        log.debug("Container was restarted")
                        break
                    if status == 'Error':
                        log.debug("State is Error")
                        break
            if job_status.get('succeeded', 0) >= 1:
                log.debug("Job succeeded")
                job_status = True
                pods = list(pykube.Pod.objects(api).filter(selector='job-name={}'.format(job_name)))
                pod = pods[0]
                break
        txt_logs = pod.get_logs()
        log.debug("Output from POD: %s", txt_logs)
        if job_status:
            stdout = txt_logs
            stderr = ''
        else:
            stdout = ''
            stderr = txt_logs
        self._clean_job(sync_transport.configmap_obj, self.job_obj)
        return SolarTransportResult.from_tuple(rc, stdout, stderr)
