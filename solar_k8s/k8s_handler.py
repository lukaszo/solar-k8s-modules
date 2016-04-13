# -*- coding: utf-8 -*-
#    Copyright 2016 Mirantis, Inc.
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

from solar.core.handlers.base import TempFileHandler
from solar.core.log import log
from solar import errors

from pykube.config import KubeConfig
from pykube.http import HTTPClient
import pykube.objects

import yaml


class K8S(TempFileHandler):
    def __init__(self, resources, handlers=None):
        self._configs = None
        super(K8S, self).__init__(resources, handlers)

    def action(self, resource, action_name):
        api = HTTPClient(KubeConfig.from_file("~/.kube/config"))
        log.debug('Executing %s %s',
                  action_name, resource.name)

        # XXX: self._configs is used in _compile_action_file via _make_args. It has to be here
        self._configs = self.prepare_configs(resource)
        action_file = self._compile_action_file(resource, action_name)
        log.debug('action_file: %s', action_file)

        # XXX: seems hacky
        obj = yaml.load(open(action_file).read())
        k8s_class = obj['kind']

        if action_name == 'run':
            k8s_class = getattr(pykube.objects, k8s_class)
            k8s_obj = k8s_class(api, obj)
            k8s_obj.create()
        elif action_name == 'update':
            raise NotImplemented(action_name)
        elif action_name == 'delete':
            raise NotImplemented(action_name)
        else:
            raise NotImplemented(action_name)

    def prepare_configs(self, resource):
        base_path = resource.db_obj.base_path
        configs_path = os.path.join(base_path, 'configs')
        if not os.path.exists(configs_path):
            return []
        configs = []
        for path in self._render_dir(resource, configs_path):
            name = os.path.basename(path)
            with open(path) as f:
                data = [line for line in f.read().splitlines() if line.strip()]
            configs.append({'name': name, 'data': data})
        return configs

    def _make_args(self, resource):
        args = super(K8S, self)._make_args(resource)
        if self._configs:
            args['_configs'] = self._configs
        return args


