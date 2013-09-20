#!/usr/bin/env python
#-*- coding: utf-8 -*-

from __future__ import unicode_literals

import unittest

from ocdlib.Config import (Config, getLogFormat,
    SectionNotFoundException, NoConfigOptionFoundException)
from ocdlib.SystemCheck import RUNNING_ON_WINDOWS


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self.config = Config()

    def tearDown(self):
        self.config._reset()
        del self.config

    def testDefaultPathsExistPerOS(self):
        self.assertTrue(self.config.WINDOWS_DEFAULT_PATHS)
        self.assertTrue(self.config.LINUX_DEFAULT_PATHS)

    def testConfigGetsFilledWithSystemDefaults(self):
        # WINDOWS_DEFAULT_PATHS = {
        #     'global': {
        #         'log_dir': u'c:\\tmp',
        #         'state_file': u'c:\\opsi.org\\opsiclientd\\state.json',
        #         'timeline_db': u'c:\\opsi.org\\opsiclientd\\timeline.sqlite',
        #         'server_cert_dir': u'c:\\opsi.org\\opsiclientd\\server-certs'
        #     },
        #     'cache_service': {
        #         'storage_dir': u'c:\\opsi.org\\cache',
        #     },
        # }

        # LINUX_DEFAULT_PATHS = {
        #     'global': {
        #         'log_dir': os.path.join('/var', 'log', 'opsi-client-agent'),
        #         'state_file': os.path.join('/etc', 'opsi-client-agent', 'state.json'),
        #         'timeline_db': os.path.join('/etc', 'opsi-client-agent', 'timeline.sqlite'),
        #         'server_cert_dir': os.path.join('/var', 'lib', 'opsi-client-agent', 'opsiclientd')
        #     },
        #     'cache_service': {
        #         'storage_dir': os.path.join('/var', 'cache', 'opsi-client-agent')
        #     },
        # }
        self.assertNotEqual('', self.config.get('global', 'log_dir'))
        self.assertNotEqual('', self.config.get('global', 'state_file'))
        self.assertNotEqual('', self.config.get('global', 'timeline_db'))
        self.assertNotEqual('', self.config.get('global', 'server_cert_dir'))

        self.assertNotEqual('', self.config.get('cache_service', 'storage_dir'))


    def testConfigGetsFilledWithSystemSpecificValues(self):
        self.assertNotEqual('', self.config.get('global', 'config_file'))
        self.assertNotEqual('', self.config.get('global', 'server_cert_dir'))

        self.assertNotEqual('', self.config.get('cache_service', 'storage_dir'))
        self.assertNotEqual('', self.config.get('cache_service', 'extension_config_dir'))
        self.assertNotEqual('', self.config.get('global', 'config_file'))
        self.assertNotEqual('', self.config.get('global', 'state_file'))
        self.assertNotEqual('', self.config.get('global', 'timeline_db'))
        self.assertNotEqual('', self.config.get('global', 'log_dir'))

        if RUNNING_ON_WINDOWS:
            self.assertNotEqual('', self.config.get('system', 'program_files_dir'))

    def testGettingUnknownSectionFails(self):
        self.assertRaises(SectionNotFoundException, self.config.get, 'nothing', 'bla')

    def testGettingUnknownOptionFails(self):
        self.assertRaises(NoConfigOptionFoundException, self.config.get, 'global', 'non_existing_option')


class LogFormatTestCase(unittest.TestCase):
    def testContainsModulename(self):
        modulename = 'asdfghj'
        self.assertTrue(modulename in getLogFormat(modulename))

    def testFormattingUses30CharactersForName(self):
        modulename = 'olol'
        self.assertEquals(
            '[%l] [%D] [ olol                          ] %M   (%F|%N)',
            getLogFormat(modulename)
        )


if __name__ == '__main__':
    unittest.main()
