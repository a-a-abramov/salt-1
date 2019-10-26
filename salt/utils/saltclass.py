# -*- coding: utf-8 -*-
# Import Python libs
from __future__ import absolute_import, print_function, unicode_literals
import os
import logging
from itertools import chain
from copy import deepcopy
from fnmatch import fnmatch
from collections import OrderedDict
from jinja2 import FileSystemLoader, Environment
import re

# Import Salt libs
import salt.utils.path
import salt.utils.yaml
from salt.exceptions import SaltException

# Import 3rd-party libs
from salt.ext import six

log = logging.getLogger(__name__)


def dict_merge(target, subject, path=None):
    '''
    Merge target <---merge-into---- subject recursively. Override (^) logic here.
    '''
    # TODO: not sure if we should use shallow or deep copy in this function.
    # Right now deep is used
    if not isinstance(target, dict) or not isinstance(subject, dict):
        raise SaltException('Illegal merge')
    if path is None:
        path = []

    for key in subject:
        # merging in new key is simple
        if key not in target:
            target[key] = deepcopy(subject[key])
            continue

        # both values are lists - extend or override
        if isinstance(target[key], list) and isinstance(subject[key], list):
            if subject[key] and subject[key][0] == '^':
                target[key] = deepcopy(subject[key])
                target[key].pop(0)
            else:
                target[key].extend(subject[key])

        # both values are dicts - recurse
        elif isinstance(target[key], dict) and isinstance(subject[key], dict):
            dict_merge(target[key], subject[key], path + [six.text_type(key)])

        # in all other cases value from subject overwrites value from object
        else:
            target[key] = deepcopy(subject[key])
    return target


def find_by_re(struct, pattern, path=None, pop_orphans=True):
    if path is None:
        path = []
    result = []
    if isinstance(struct, dict):
        for key, val in struct.items():
            result.extend(find_by_re(val, pattern, path + [key], pop_orphans))
    elif isinstance(struct, list):
        # here is the cheapest place to pop orphaned ^
        if pop_orphans and len(struct) > 0:
            if struct[0] == '^':
                struct.pop(0)
            elif struct[0] == r'\^':
                struct[0] = '^'
        for index, element in enumerate(struct):
            result.extend(find_by_re(element, pattern, path + [index], pop_orphans))
    else:
        result.extend([(path, match) for match in pattern.finditer(six.text_type(struct))])
    return result


def get_variable_value(variable, dct):
    '''
    Retrieve original value from ${xx:yy:zz} to be expanded
    :param variable: "${xx:yy:zz}" OR "xx:yy:zz" OR ["xx", "yy", "zz"]
    :param dct: where to look for the value
    :return: value from variable
    '''
    if isinstance(variable, six.string_types):
        if fnmatch(variable, "${*}"):
            path = variable[2:-1].split(':')
        else:
            path = variable.split(':')
    elif isinstance(variable, list):
        path = variable
    else:
        raise SaltException('Can\'t find value for {}'.format(six.text_type(variable)))
    for p in path:
        try:
            dct = dct[p]
        except (KeyError, TypeError):
            raise SaltException('Unable to expand {}'.format(variable))
    return dct


def substitute(struct, path, original, variable, value):
    """
    Substitute all occurrences of variable in original with value and save to struct at path
    """
    for p in path[:-1]:
        struct = struct[p]
    if isinstance(value, (list, dict)):
        if struct[path[-1]] == variable:
            struct[path[-1]] = value
        else:
            raise SaltException('Type mismatch on variable {} expansion'.format(variable))
    else:
        struct[path[-1]] = original.replace(variable, six.text_type(value))


class MockDict(dict):
    def __getitem__(self, item):
        return item


class SaltClass(object):

    def __init__(self, salt_data, mock=False):
        self._salt_data = salt_data
        self._class_paths = None
        self._node_paths = None
        self.class_registry = dict()

    def __getattr__(self, name):
        if name not in self._salt_data:
            raise AttributeError
        return self._salt_data[name]

    @property
    def class_paths(self):
        if self._class_paths is not None:
            return self._class_paths
        self._class_paths = {}
        for dirpath, dirnames, filenames in salt.utils.path.os_walk(os.path.join(self.path, 'classes'),
                                                                    followlinks=True):
            for filename in filenames:
                # Die if there's an X.yml file and X directory in the same path
                if filename[:-4] in dirnames:  # [:-4] trims .yml
                    raise SaltException('Conflict in class file structure - file {}/{} and directory {}/{}. '
                                        .format(dirpath, filename, dirpath, filename[:-4]))
                abs_path = os.path.join(dirpath, filename)
                rel_path = abs_path[len(str(os.path.join(self.path, 'classes' + os.sep))):]
                if rel_path.endswith(os.sep + 'init.yml'):
                    name = str(rel_path[:-len(os.sep + 'init.yml')]).replace(os.sep, '.')
                else:
                    name = str(rel_path[:-len('.yml')]).replace(os.sep, '.')
                self._class_paths[name] = abs_path
        return self._class_paths

    @property
    def node_paths(self):
        if self._node_paths is not None:
            return self._node_paths
        self._node_paths = {}
        for dirpath, _, filenames in salt.utils.path.os_walk(os.path.join(self.path, 'nodes'), followlinks=True):
            for filename in filenames:
                if not fnmatch(filename, '*.yml'):
                    pass
                # TODO: rpartition
                minion_id = filename.rsplit('.', 1)[0]
                if minion_id in self._node_paths:
                    raise SaltException('{} defined more than once. '
                                        'Nodes can only be defined once per inventory.'
                                        .format(minion_id))
                self._node_paths[minion_id] = os.path.join(dirpath, filename)
        return self._node_paths

    # pillars, classes, states, environment
    def render(self, node_name):
        node = Node(node_name, self)
        pprint(node.get_class_order())
        pprint(node.get_raw_tree())
        pass


class Klass(object):

    def __init__(self, name, sc, _merged=None):
        '''
        Create instance of class (saltclass-class, not python-class) and recurse through it's children.
        :param name: class name
        :param sc: fully initialized SaltClass object
        '''
        self.name = name
        self.sc = sc
        self._seen = set() if _merged is None else _merged
        self.raw = None

        self.classes = OrderedDict()  # class_name:Klass
        self.pillars = {}
        self.states = []
        self.environment = None  # TODO: set default from salt here

        self._expanded_class_subtree = None
        self._build()

    def get_class_order(self):
        if self._expanded_class_subtree is not None:
            return self._expanded_class_subtree
        self._expanded_class_subtree = OrderedDict()
        if not self.classes:
            return self._expanded_class_subtree
        for cls in self.classes.values():
            #if cls is not None:
                self._expanded_class_subtree.update(cls.get_class_order())
        self._expanded_class_subtree.update(self.classes.items())
        return self._expanded_class_subtree

    def get_raw_tree(self, full=False):
        children = []
        if self.classes:
            for cls in self.classes.itervalues():
                children.append(cls.get_raw_tree(full))
        if full:
            result = {}
            for field in ['pillars', 'states', 'environment']:
                if field in self.raw:
                    result[field] = self.raw[field]
            result['classes'] = children
            return {self.name: result}
        else:
            return {self.name: children}

    def expand_all(self):
        def _expand(struct, pattern):
            for i in xrange(self.sc.opts['max_expansion_passes']):
                for path, match in find_by_re(struct, pattern):
                    variable = match.group(0)
                    value = variable[2:] if variable.startswith('\\') else get_variable_value(variable, self.pillars)
                    if isinstance(struct, six.string_types):
                        struct = struct.replace(variable, value)
                    else:
                        substitute(struct, path, match.string, variable, value)
                else:
                    break
            return struct

        pattern = re.compile(r'(\\)?\${.*?}')
        self.pillars = _expand(self.pillars, pattern)
        self.states = _expand(self.states, pattern)
        self.environment = _expand(self.environment, pattern)

    def _build(self):
        self._raw_load()
        self._raw_validate()
        self._preprocess_classes()
        self._recurse_classes()
        #self._merge()

        # reset _seen for future recursions
        # self._seen = None

    def _raw_load(self):
        try:
            self.raw = salt.utils.yaml.safe_load(self._render_jinja())
        except salt.utils.yaml.YAMLError as e:
            log.error('YAML rendering exception for file %s:\n%s', self.path, e)
        if self.raw is None:
            log.warning('Unable to render yaml from %s', self.path)
            self.raw = {}
        return self.raw

    def _raw_validate(self):
        # here we mean that list is list of strings
        type_mapping = [('classes', list),
                        ('pillars', dict),
                        ('states', list),
                        ('environment', six.string_types)]
        for field, type_ in type_mapping:
            if field not in self.raw:
                continue
            if not isinstance(self.raw[field], type_):
                raise SaltException('{} in {} is not a valid instance of {}'
                                    .format(field, self.path, str(type_)))
            if isinstance(self.raw[field], list) and any([not isinstance(x, list) for x in self.raw[field]]):
                raise SaltException('{} must be list of strings'.format(field))
        pass

    def _render_jinja(self):
        j_env = Environment(loader=FileSystemLoader(os.path.dirname(self.path)))
        j_env.globals.update({
            'opts': self.sc.opts,
            'salt': self.sc.salt,
            'grains': self.sc.grains,
            'pillar': self.sc.pillar
        })
        j_render = j_env.get_template(os.path.basename(self.path)).render()
        return j_render

    def _preprocess_classes(self):

        def is_glob(s):
            if s is None or not isinstance(s, six.string_types):
                return False, False
            is_prefix_glob = True if s.startswith('.') else False
            is_suffix_glob = True if s.endswith('*') else False
            return is_prefix_glob, is_suffix_glob

        if 'classes' not in self.raw:
            return
        for entry in self.raw['classes']:
            pref, suff = is_glob(entry)
            if not (pref or suff):  # not a glob
                self.classes[entry] = None  # entry is actual class name
                continue
            self_init_notation = self.path.endswith('init.yml')
            ancestor, _, _ = self.name.rpartition('.')
            glob_ = entry

            # If base_class A.B defined with file <>/classes/A/B/init.yml, glob . is ignored
            # If base_class A.B defined with file <>/classes/A/B.yml, glob . addresses
            # class A if and only if A is defined with <>/classes/A/init.yml.
            # I.e. glob . references neighbour init.yml
            if glob_.strip() == '.':
                ancestor_init_notation = self.sc.class_paths.get(ancestor, '').endswith('init.yml')
                if not self_init_notation and ancestor_init_notation:
                    self.classes[ancestor] = None
                continue

            base = ancestor if self_init_notation else self.name
            if pref:
                glob_ = base + glob_
            resolved_suffix_glob = [c for c in self.sc.class_paths.keys() if c.startswith(glob_[:-1])]
            for class_name in resolved_suffix_glob:
                self.classes[class_name] = None
            # if we're here, entry is not glob anymore but an actual class name

    def _recurse_classes(self):
        for class_name in self.classes.keys():
            if class_name in self._seen:
                # just point to already processes class
                try:
                    self.classes[class_name] = self.sc.class_registry[class_name]
                except KeyError as e:
                    raise SaltException('Possible loop in class structure. {} can\'t contain {}.'
                                        .format(self.name, class_name))
                continue
            self._seen.add(class_name)
            cls = Klass(name=class_name, sc=self.sc, _merged=self._seen)
            self.sc.class_registry[class_name] = cls
            self.classes[class_name] = cls
            self._merge(cls)
        self._merge_self()
        return

    def _merge(self, other):
        dict_merge(self.pillars, other.pillars)
        for state in other.states:
            if state not in self.states:
                self.states.append(state)
        self.environment = other.environment

    def _merge_self(self):
        dict_merge(self.pillars, self.raw.get('pillars', {}))
        for state in self.raw.get('states', []):
            if state not in self.states:
                self.states.append(state)
        if 'environment' in self.raw:
            self.environment = self.raw['environment']

    def _merge_order(self, merge_order=None):
        if merge_order is None:
            merge_order = OrderedDict()
        for cls in self.classes.values():
            cls._merge_order(merge_order)
        if self.name not in merge_order:
            merge_order[self.name] = self
        return merge_order


    @property
    def path(self):
        return self.sc.class_paths.get(self.name, None)


class Node(Klass):
    @property
    def path(self):
        return self.sc.node_paths.get(self.name, None)


import yaml
from pprint import pprint

noalias_dumper = yaml.dumper.SafeDumper
noalias_dumper.ignore_aliases = lambda self, data: True

dat = {
    "grains": {},
    "opts": {
        "max_expansion_passes": 5
    },
    "pillar": {},
    "salt": {},
    "minion_id": "fake_id9",
    "path": "/home/andrey/PycharmProjects/saltstack/tests/integration/files/saltclass/examples-new-new"
}

sclass = SaltClass(dat)
# sclass.get_data('fake_id9')
m = Klass('ord.G', sclass)
pprint(m.get_class_order().keys())
pprint(m.get_raw_tree())
pprint(m.pillars)
pprint(m.states)
pprint(m.environment)
before_pillars = find_by_re(m.pillars, re.compile(r'(\\)?\${.*?}'))
before_states = m.states[:]
before_env = m.environment
m.expand_all()

print("PILLARS:")
for path, match in before_pillars:
    print('.'.join(six.text_type(p) for p in path) + ": " + six.text_type(match.string) + ": "
          + six.text_type(get_variable_value(path, m.pillars)))

print("STATES:")
for bef, af in zip(before_states, m.states):
    if bef != af:
        print(bef + ": " + af)

print("ENVIRONMENT:")
if before_env != m.environment:
    print(before_env + ": " + m.environment)

# pprint(m.merge_order())
# yaml.dump(m.merge_tree(full=True), default_flow_style=False, stream=sys.stdout, Dumper=noalias_dumper)
