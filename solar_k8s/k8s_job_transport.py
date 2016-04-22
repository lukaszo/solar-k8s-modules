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

from solar.core.log import log
from solar.core.transports.base import SyncTransport
from solar.core.transports.base import RunTransport

from pykube.config import KubeConfig
from pykube.http import HTTPClient
import pykube.objects


class Job(pykube.objects.NamespacedAPIObject):

    version = "batch/v1"
    endpoint = "jobs"
    kind = "Job"


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
            local_root = root.replace(path, '')
            for f in files:
                with open(os.path.join(root, f), 'rb') as fd:
                    data = fd.read()
                key = os.path.join(local_root, f)
                files_data['data%d' % (num_prefix + i)] = data
                i += 1
                keys['data%d' % (num_prefix + i)] = key

        return {'keys': keys, 'files_data': files_data}

    def all_keys(self):
        datas = self.configmap_datas
        keys = {}
        for single in datas:
            keys.update(single)
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

        self.configmap_name = resource.name
        self.configmap_namespace = 'default'
        self.configmap_datas = datas

        obj = self.make_configmap_obj(datas)

        pykube.objects.ConfigMap(api, obj).create()  # wait ?

        return


class K8SJobRunTransport(RunTransport):

    def get_volume_items(self, resource):
        # XXX: it's bound to BAT logic, shound't be like that
        keys = resource._bat_transport_sync.all_keys()
        items = []
        for key, path in keys.iteritems():
            items.append({'key': key, 'path': path})
        return items

    def run(self, resource, *args, **kwargs):
        api = HTTPClient(KubeConfig.from_file('~/.kube/config'))
        # handler = resource.db_obj.handler
        command = args
        items = self.get_volume_items(resource)
        sync_transport = resource._bat_transport_sync
        # kubernetes api...
        obj = {
            # 'apiVersion': 'extensions/v1beta1',
            'apiVersion': 'batch/v1',
            'kind': 'Job',
            'metadata': {'name': 'job' + sync_transport.configmap_name},
            'spec': {'template':
                     {'metadata': {
                         'name': 'cnts' + sync_transport.configmap_name
                         },
                      'spec': {
                          'containers': [
                              {'name': 'cnt' + sync_transport.configmap_name,
                               # 'image': 'handler-%s' % handler,
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
                                'name': 'job-config',
                                'items': items
                               }}
                          ],
                          'restartPolicy': 'Never'
                      }}}}
        pykube.objects.Job(api, obj).create()
