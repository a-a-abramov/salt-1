# -*- coding: utf-8 -*-

# Import python libs
from __future__ import absolute_import, print_function, unicode_literals
import os

# Import Salt Testing libs
from tests.support.mixins import LoaderModuleMockMixin
from tests.support.unit import TestCase, skipIf
from tests.support.mock import NO_MOCK, NO_MOCK_REASON

# Import Salt Libs
import salt.pillar.saltclass as saltclass
from salt.exceptions import SaltException

base_path = os.path.dirname(os.path.realpath(__file__))

fake_pillar = {}
fake_args = ({'path': os.path.abspath(
    os.path.join(base_path, '..', '..', 'integration',
                 'files', 'saltclass', 'examples-new-new'))})
fake_opts = {}
fake_salt = {}
fake_grains = {}


@skipIf(NO_MOCK, NO_MOCK_REASON)
class SaltclassTestCase(TestCase, LoaderModuleMockMixin):
    '''
    Tests for salt.pillar.saltclass
    '''

    def setup_loader_modules(self):
        return {saltclass: {'__opts__': fake_opts,
                            '__salt__': fake_salt,
                            '__grains__': fake_grains}}

    def prnt(self):
        import salt.utils.yaml as yaml
        import sys
        extp_data = saltclass.ext_pillar('salt-master.sapphire.example.net', {}, fake_args)
        yaml.dump(extp_data, stream=sys.stdout)
