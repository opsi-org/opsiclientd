#! /usr/bin/env python
# -*- coding: utf-8 -*-

import unittest

from ocdlib.Config import (Config, getLogFormat,
    SectionNotFoundException, NoConfigOptionFoundException)
from ocdlib.SystemCheck import RUNNING_ON_WINDOWS


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self.config = Config()

    def tearDown(self):
        try:
            self.config._reset()
        except AttributeError:
            print("Whoops, we are missing something!")

        del self.config

    def testDefaultPathsExistPerOS(self):
        self.assertTrue(self.config.WINDOWS_DEFAULT_PATHS)
        self.assertTrue(self.config.LINUX_DEFAULT_PATHS)

    def testConfigGetsFilledWithSystemDefaults(self):
        self.assertNotEqual('', self.config.get('global', 'log_dir'))
        self.assertNotEqual('', self.config.get('global', 'state_file'))
        self.assertNotEqual('', self.config.get('global', 'timeline_db'))
        self.assertNotEqual('', self.config.get('global', 'server_cert_dir'))

        self.assertNotEqual('', self.config.get('cache_service', 'storage_dir'))

        for section in ('log_dir', 'state_file', 'timeline_db', 'server_cert_dir'):
            if RUNNING_ON_WINDOWS:
                self.assertTrue(self.config.get('global', section).startswith('c:'))
            else:
                self.assertTrue(self.config.get('global', section).startswith('/'))

        if RUNNING_ON_WINDOWS:
            self.assertTrue(self.config.get('cache_service', 'storage_dir').startswith('c:'))
        else:
            self.assertTrue(self.config.get('cache_service', 'storage_dir').startswith('/'))

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
