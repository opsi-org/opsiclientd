#! /usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import unicode_literals

import os
import shutil
import tempfile
from contextlib import contextmanager
import unittest

from ocdlib.Config import (Config, getLogFormat,
    SectionNotFoundException, NoConfigOptionFoundException)
from ocdlib.SystemCheck import RUNNING_ON_WINDOWS


@contextmanager
def workInTemporaryDirectory(tempDir=None):
    """
    Creates a temporary folder to work in. Deletes the folder afterwards.

    :param tempDir: use the given dir as temporary directory. Will not \
be deleted if given.
    """
    temporary_folder = tempDir or tempfile.mkdtemp()
    with cd(temporary_folder):
        try:
            yield temporary_folder
        finally:
            if not tempDir:
                try:
                    shutil.rmtree(temporary_folder)
                except OSError:
                    pass


@contextmanager
def cd(path):
    'Change the current directory to `path` as long as the context exists.'

    old_dir = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_dir)


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

    def testRotatingLogfile(self):
        with workInTemporaryDirectory() as tempDir:
            dummyConfig = os.path.join(tempDir, 'config')
            logFile = os.path.join(tempDir, 'testlog.log')

            with open(logFile, 'w') as f:
                pass

            with open(dummyConfig, 'w') as f:
                f.write("""[global]
log_file = {0}""".format(logFile))

            self.config.set('global', 'config_file', dummyConfig)
            self.config.set('global', 'log_dir', tempDir)

            # First rotation
            self.config.readConfigFile(keepLog=False)
            print(os.listdir(tempDir))
            assert os.path.exists(os.path.join(tempDir, 'testlog.log.0'))

            # Second rotation
            self.config.readConfigFile(keepLog=False)
            print(os.listdir(tempDir))
            assert os.path.exists(os.path.join(tempDir, 'testlog.log.1'))


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
