# -*- coding: utf-8 -*-
'''
Helper runner for saltclass ext_pillar/master_top
'''
from __future__ import absolute_import, print_function, unicode_literals

# Import python libs
import logging

# Import salt libs
import salt.utils.saltclass
from salt.exceptions import SaltRunnerError

log = logging.getLogger(__name__)


def compile_minion_data(minion):
    from pprint import pprint
    print('dir')
    pprint(dir())
    print('globals')
    pprint(globals())
    print('locals')
    pprint(locals())
    minion_pillars = salt.utils.saltclass
    return minion
