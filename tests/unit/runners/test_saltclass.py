# -*- coding: utf-8 -*-
'''
Unit tests for the saltclass runner
'''

# Import Python Libs
from __future__ import absolute_import, print_function, unicode_literals
import logging

# Import Salt Testing Libs
from tests.support.mixins import LoaderModuleMockMixin
from tests.support.unit import skipIf, TestCase
from tests.support.mock import (
    MagicMock,
    Mock,
    patch,
    NO_MOCK,
    NO_MOCK_REASON,
    ANY,
    call
)

# Import salt libs
from salt.ext import six
import salt.runners.saltclass

log = logging.getLogger(__name__)


class SaltClassRunnerTest(TestCase, LoaderModuleMockMixin):

    def setup_loader_modules(self):
        return {salt.runners.saltclass: {
            '__opts__': {
                'saltclass': {
                    'path': '/home/andrey/PycharmProjects/saltstack/tests/integration/files/saltclass/examples-new-new',
                    'max_expansion_passes': 5}}
        }}

    def test_test(self):
        from pprint import pprint
        pprint(salt.runners.saltclass.compile_minion_data('minion_id'))
