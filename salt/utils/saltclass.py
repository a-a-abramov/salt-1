# -*- coding: utf-8 -*-
# Import Python libs
from __future__ import absolute_import, print_function, unicode_literals
import os
import re
import logging
from collections import OrderedDict
from jinja2 import FileSystemLoader, Environment

# Import Salt libs
import salt.utils.path
import salt.utils.yaml
from salt.exceptions import SaltException

# Import 3rd-party libs
from salt.ext import six

log = logging.getLogger(__name__)


def _render_jinja(_file, salt_data):
    j_env = Environment(loader=FileSystemLoader(os.path.dirname(_file)))
    j_env.globals.update({
        'opts': salt_data['__opts__'],
        'salt': salt_data['__salt__'],
        'grains': salt_data['__grains__'],
        'pillar': salt_data['__pillar__'],
    })
    j_render = j_env.get_template(os.path.basename(_file)).render()
    return j_render


def _render_yaml(_file, salt_data):
    result = None
    try:
        result = salt.utils.yaml.safe_load(_render_jinja(_file, salt_data))
    except salt.utils.yaml.YAMLError as e:
        log.error('YAML rendering exception for file %s:\n%s', _file, e)
    if result is None:
        log.warning('Unable to render yaml from %s', _file)
        return {}
    return result


def dict_merge(m_target, m_object, path=None, reverse=False):
    '''
    Merge m_target <---merge-into---- m_object recursively. Override (^) logic here.
    '''
    if path is None:
        path = []

    for key in m_object:
        if key in m_target:
            if isinstance(m_target[key], list) and isinstance(m_object[key], list):
                if not reverse:
                    if m_object[key] and m_object[key][0] == '^':
                        m_object[key].pop(0)
                        m_target[key] = m_object[key]
                    else:
                        m_target[key].extend(m_object[key])
                else:
                    # In reverse=True mode if target list (from higher level class)
                    # already has ^ , then we do nothing
                    if m_target[key] and m_target[key][0] == '^':
                        pass
                    # if it doesn't - merge to the beginning
                    else:
                        m_target[key][0:0] = m_object[key]
            elif isinstance(m_target[key], dict) and isinstance(m_object[key], dict):
                dict_merge(m_target[key], m_object[key], path + [six.text_type(key)], reverse=reverse)
            elif m_target[key] == m_object[key]:
                pass
            else:
                # If we're here a and b has different types.
                # Update in case reverse=True
                if not reverse:
                    m_target[key] = m_object[key]
                # And just pass in case reverse=False since key a already has data from higher levels
                else:
                    pass
        else:
            m_target[key] = m_object[key]
    return m_target


def _get_variable_value(variable, pillar_data):
    '''
    Retrieve original value from ${xx:yy:zz} to be expanded
    '''
    rv = pillar_data
    for i in variable[2:-1].split(':'):
        try:
            rv = rv[i]
        except KeyError:
            raise SaltException('Unable to expand {}'.format(variable))
    return rv


def _get_variables_from_pillar(text_pillar, escaped=True):
    '''
    Get variable names from this pillar.
    'blah blah ${key1}${key2} blah ${key1}' will result in {'${key1}', '${key2}'}
    :param text_pillar: string pillar
    :param escaped: should we match \${escaped:reference} or ${not}
    :return: set of matched substrings from pillar
    '''
    matches_iter = re.finditer(r'(\\)?\${.*?}', six.text_type(text_pillar))
    result = set()
    if not matches_iter:
        pass
    for match in matches_iter:
        if escaped or not six.text_type(match.group()).startswith('\\'):
            result.add(match.group())
    return result


def _update_pillar(pillar_path, variable, value, pillar_data):
    rv = pillar_data
    for key in pillar_path[:-1]:
        rv = rv[key]
    if isinstance(value, (list, dict)):
        if rv[pillar_path[-1]] == variable:
            rv[pillar_path[-1]] = value
        else:
            raise SaltException('Type mismatch on variable {} expansion'.format(variable))
    else:
        rv[pillar_path[-1]] = six.text_type(rv[pillar_path[-1]]).replace(variable, six.text_type(value))
    return rv[pillar_path[-1]]


def _find_expandable_pillars(pillar_data, **kwargs):
    '''
    Recursively look for variable to expand in nested dicts, lists, strings
    :param pillar_data: structure to look in
    :return: list of tuples [(path, variable), ... ] where for pillar X:Y:Z path is ['X', 'Y', 'Z']
    and variable is a single ${A:B:C} expression. For a text pillar with several different variables inside
    will return several entries in result.
    '''
    pillar = kwargs.get('pillar', pillar_data)
    path = kwargs.get('path', [])
    result = kwargs.get('result', [])
    escaped = kwargs.get('escaped', True)

    if isinstance(pillar, dict):
        for k, v in pillar.items():
            _find_expandable_pillars(pillar_data=pillar_data, pillar=v, path=path + [k],
                                     result=result, escaped=escaped)
    elif isinstance(pillar, list):
        # here is the cheapest place to pop orphaned ^
        if len(pillar) > 0 and pillar[0] == '^':
            pillar.pop(0)
        elif len(pillar) > 0 and pillar[0] == r'\^':
            pillar[0] = '^'
        for i, elem in enumerate(pillar):
            _find_expandable_pillars(pillar_data=pillar_data, pillar=elem, path=path + [i],
                                     result=result, escaped=escaped)
    else:
        for variable in _get_variables_from_pillar(six.text_type(pillar), escaped):
            result.append((path, variable))

    return result


def expand_variables(pillar_data):
    '''
    Open every ${A:B:C} variable in pillar_data
    '''
    path_var_mapping = _find_expandable_pillars(pillar_data, escaped=False)
    # TODO: remove hardcoded 5 into options
    for i in range(5):
        new_path_var_mapping = []
        for path, variable in path_var_mapping:
            # get value of ${A:B:C}
            value = _get_variable_value(variable, pillar_data)

            # update pillar '${A:B:C}' -> value of ${A:B:C}
            pillar = _update_pillar(path, variable, value, pillar_data)

            # check if we got more expandable variable (in case of nested expansion)
            new_variables = _find_expandable_pillars(pillar, escaped=False)

            # update next iteration's variable
            new_path_var_mapping.extend([(path + p, v) for p, v in new_variables])

        # break if didn't find any cases of nested expansion
        if not new_path_var_mapping:
            break
        path_var_mapping = new_path_var_mapping

    return pillar_data


def _validate(name, data):
    '''
    Make sure classes, pillars, states and environment are of appropriate data types
    '''
    # TODO: looks awful, there's a better way to write this
    if 'classes' in data:
        data['classes'] = [] if data['classes'] is None else data['classes']  # None -> []
        if not isinstance(data['classes'], list):
            raise SaltException('Classes in {} is not a valid list'.format(name))
    if 'pillars' in data:
        data['pillars'] = {} if data['pillars'] is None else data['pillars']  # None -> {}
        if not isinstance(data['pillars'], dict):
            raise SaltException('Pillars in {} is not a valid dict'.format(name))
    if 'states' in data:
        data['states'] = [] if data['states'] is None else data['states']  # None -> []
        if not isinstance(data['states'], list):
            raise SaltException('States in {} is not a valid list'.format(name))
    if 'environment' in data:
        data['environment'] = '' if data['environment'] is None else data['environment']  # None -> ''
        if not isinstance(data['environment'], six.string_types):
            raise SaltException('Environment in {} is not a valid string'.format(name))
    return


def _resolve_prefix_glob(prefix_glob, salt_data):
    '''
    Resolves prefix globs
    '''
    result = [c for c in salt_data['class_paths'].keys() if c.startswith(prefix_glob[:-1])]

    # Concession to usual globbing habits from operating systems:
    # include class A.B to result of glob A.B.* resolution
    # if the class is defined with <>/classes/A/B/init.yml (but not with <>/classes/A/B.yml!)
    # TODO: should we remove this? We already fail hard if there's a B.yml file and B directory in the same path
    if prefix_glob.endswith('.*') and salt_data['class_paths'].get(prefix_glob[:-2], '').endswith('/init.yml'):
        result.append(prefix_glob[:-2])
    return result


def resolve_classes_glob(base_class, glob, salt_data):
    '''
    Finds classes for the glob. Can't return other globs.

    :param str base_class: class where glob was found in - we need this information to resolve suffix globs
    :param str glob:
    - prefix glob - A.B.* or A.B*
    - suffix glob - .A.B
    - combination of both - .A.B.*
    - special - . (single dot) - to address "local" init.yml - the one found in the same directory
    :param dict salt_data: salt_data
    :return: list of strings or empty list - classes, resolved from the glob
    '''
    base_class_init_notation = salt_data['class_paths'].get(base_class, '').endswith('init.yml')
    ancestor_class, _, _ = base_class.rpartition('.')

    # If base_class A.B defined with file <>/classes/A/B/init.yml, glob . is ignored
    # If base_class A.B defined with file <>/classes/A/B.yml, glob . addresses
    # class A if and only if A is defined with <>/classes/A/init.yml.
    # I.e. glob . references neighbour init.yml
    if glob.strip() == '.':
        if base_class_init_notation:
            return []
        else:
            ancestor_class_init_notation = salt_data['class_paths'].get(ancestor_class, '').endswith('init.yml')
            return [ancestor_class] if ancestor_class_init_notation else []
    else:
        if not base_class_init_notation:
            base_class = ancestor_class
        if glob.startswith('.'):
            glob = base_class + glob
        if glob.endswith('*'):
            return _resolve_prefix_glob(glob, salt_data)
        else:
            return [glob]  # if we're here glob is not glob anymore but actual class name


def expand_class(cls, salt_data):
    cls_filepath = salt_data['class_paths'].get(cls)
    if not cls_filepath:
        log.warning('%s: Class definition not found', cls)
        return {}
    expanded_class = _render_yaml(cls_filepath, salt_data)
    _validate(cls, expanded_class)
    if 'classes' in expanded_class:
        resolved_classes = []
        for c in reversed(expanded_class['classes']):
            if c is not None and isinstance(c, six.string_types):
                # Resolve globs
                if c.endswith('*') or c.startswith('.'):
                    resolved_classes.extend(reversed(resolve_classes_glob(cls, c, salt_data)))
                else:
                    resolved_classes.append(c)
            else:
                raise SaltException('Nonstring item in classes list in class {} - {}. '.format(cls, str(c)))
        expanded_class['classes'] = resolved_classes[::-1]
    return expanded_class


def get_expanded_classes(cls, salt_data, cls_dict=None, seen_classes=None):
    cls = cls if isinstance(cls, list) else [cls]
    cls_dict = {} if cls_dict is None else cls_dict
    seen_classes = set() if seen_classes is None else seen_classes

    for c in cls:
        if c not in seen_classes:
            seen_classes.add(c)
            cls_dict[c] = expand_class(c, salt_data)
            if cls_dict[c].get('classes'):
                get_expanded_classes(cls_dict[c].get('classes'), salt_data, cls_dict=cls_dict, seen_classes=seen_classes)
    return cls_dict


def get_ordered_class_list(cls, cls_dict, seen_classes=None):
    ord_subclasses = []
    seen_classes = set() if seen_classes is None else seen_classes
    for c in cls_dict.get(cls, {}).get('classes', []):
        if c not in seen_classes:
            seen_classes.add(c)
            ord_subclasses.extend(get_ordered_class_list(c, cls_dict, seen_classes=seen_classes))
    return ord_subclasses + [cls]


def get_class_list_by_level(classes_by_levels, cls_dict, current_level=0, seen_classes=None):
    seen_classes = set() if seen_classes is None else seen_classes
    for cls in classes_by_levels.get(current_level):
        if cls not in seen_classes:
            seen_classes.add(cls)

            subclasses = cls_dict.get(cls, {}).get('classes', [])
            if not subclasses:
                continue
            if not current_level + 1 in classes_by_levels:
                classes_by_levels[current_level + 1] = []
            classes_by_levels[current_level + 1].extend(subclasses)
            get_class_list_by_level(classes_by_levels, cls_dict, current_level + 1, seen_classes)
    return classes_by_levels


def remove_duplicates(class_list):
    tmp = []
    for c in class_list:
        if c not in tmp:
            tmp.append(c)
    return tmp


def get_class_paths(salt_data):
    salt_data['class_paths'] = {}
    for dirpath, dirnames, filenames in salt.utils.path.os_walk(os.path.join(salt_data['path'], 'classes'),
                                                                followlinks=True):
        for filename in filenames:
            # Die if there's an X.yml file and X directory in the same path
            if filename[:-4] in dirnames:   # [:-4] trims .yml
                raise SaltException('Conflict in class file structure - file {}/{} and directory {}/{}. '
                                    .format(dirpath, filename, dirpath, filename[:-4]))
            abs_path = os.path.join(dirpath, filename)
            rel_path = abs_path[len(str(os.path.join(salt_data['path'], 'classes' + os.sep))):]
            if rel_path.endswith(os.sep + 'init.yml'):
                name = str(rel_path[:-len(os.sep + 'init.yml')]).replace(os.sep, '.')
            else:
                name = str(rel_path[:-len('.yml')]).replace(os.sep, '.')
            salt_data['class_paths'][name] = abs_path
    return OrderedDict(((k, salt_data['class_paths'][k]) for k in sorted(salt_data['class_paths'])))


def get_saltclass_data(node_data, salt_data):
    salt_data['class_paths'] = get_class_paths(salt_data)
    node_data['classes'] = get_node_classes(node_data, salt_data)
    expanded_classes = get_expanded_classes(node_data['classes'], salt_data)

    # We would merge pillars and compose list of states while iterating over this list
    ordered_class_list = []
    for cls in node_data['classes']:
        ordered_class_list.extend(get_ordered_class_list(cls, expanded_classes))
    ordered_class_list = remove_duplicates(ordered_class_list)

    # This list is for representation in __saltclass__ dict in pillars ONLY.
    # The order is the same as in reclass to keep backward compatibility.
    classes_repr = []
    for cls in node_data['classes']:
        classes_by_levels = get_class_list_by_level({0: [cls]}, expanded_classes)

        for level in sorted(classes_by_levels.keys(), reverse=True)[:-1]:
            classes_repr.extend(classes_by_levels[level])
    classes_repr.extend(node_data['classes'])
    classes_repr = remove_duplicates(classes_repr)

    # Build state list and get 'environment' variable
    ordered_state_list = []
    environment = node_data.get('environment', 'base')
    for cls in ordered_class_list:
        class_pillars = expanded_classes.get(cls, {}).get('pillars', {}) or {}
        class_states = expanded_classes.get(cls, {}).get('states', []) or []
        environment = expanded_classes.get(cls, {}).get('environment') or environment
        dict_merge(salt_data['__pillar__'], class_pillars)
        ordered_state_list.extend([state for state in class_states if state not in ordered_state_list])
    ordered_state_list.extend(node_data.get('states', []))
    dict_merge(salt_data['__pillar__'], node_data.get('pillars', {}))

    # Expand ${xx:yy:zz} and pop override (^) markers
    salt_data['__pillar__'] = expand_variables(salt_data['__pillar__'])
    salt_data['__classes__'] = classes_repr
    salt_data['__states__'] = ordered_state_list
    return salt_data['__pillar__'], salt_data['__classes__'], salt_data['__states__'], environment


def get_node_data(minion_id, salt_data):
    '''
    Build node_data structure from node definition file
    '''
    node_file = ''
    for dirpath, _, filenames in salt.utils.path.os_walk(os.path.join(salt_data['path'], 'nodes'), followlinks=True):
        for minion_file in filenames:
            if minion_file == '{0}.yml'.format(minion_id):
                if node_file:
                    raise SaltException('Definition of node {} in {} collides with definition in {}. '
                                        'Nodes can only be defined once per inventory.'
                                        .format(minion_id, node_file, os.path.join(dirpath, minion_file)))
                node_file = os.path.join(dirpath, minion_file)

    # Load the minion_id definition if existing, else an empty dict

    if node_file:
        result = _render_yaml(node_file, salt_data)
        _validate(minion_id, result)
        return result
    else:
        log.info('%s: Node definition not found in saltclass', minion_id)
        return {}


def get_node_classes(node_data, salt_data):
    '''
    Extract classes from node_data structure. Resolve here all globs found in it. Can't do it with resolve_classes_glob
    since node globs are more strict and support prefix globs only.
    :return: list of extracted classes
    '''
    result = []
    for c in node_data.get('classes', []):
        if c.startswith('.'):
            raise SaltException('Unsupported glob type in {} - \'{}\'. '
                                'Only A.B* type globs are supported in node definition. '
                                .format(salt_data['minion_id'], c))
        elif c.endswith('*'):
            resolved_node_glob = _resolve_prefix_glob(c, salt_data)
            result.extend(sorted(resolved_node_glob))
        else:
            result.append(c)
    return result


def get_pillars(minion_id, salt_data):
    '''
    :return: dict of pillars with additional meta field __saltclass__ which has info about classes, states, and env
    '''
    node_data = get_node_data(minion_id, salt_data)
    pillars, classes, states, environment = get_saltclass_data(node_data, salt_data)

    # Build the final pillars dict
    pillars_dict = dict()
    pillars_dict['__saltclass__'] = {}
    pillars_dict['__saltclass__']['states'] = states
    pillars_dict['__saltclass__']['classes'] = classes
    pillars_dict['__saltclass__']['environment'] = environment
    pillars_dict['__saltclass__']['nodename'] = minion_id
    pillars_dict.update(pillars)

    return pillars_dict


def get_tops(minion_id, salt_data):
    '''
    :return: list of states for a minion
    '''
    node_data = get_node_data(minion_id, salt_data)
    _, _, states, environment = get_saltclass_data(node_data, salt_data)

    tops = dict()
    tops[environment] = states

    return tops
