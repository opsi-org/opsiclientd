#! /usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import unicode_literals

import os
import shutil
import tempfile
from contextlib import contextmanager

from ocdlib.Config import Config

import pytest


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


@pytest.fixture
def config():
    config = Config()
    try:
        yield config
    finally:
        config._reset()


def testGettingUnknownSectionFails(config):
    with pytest.raises(ValueError):
        config.get('nothing', 'bla')


def testGettingUnknownOptionFails(config):
    with pytest.raises(ValueError):
        config.get('global', 'non_existing_option')


def testRotatingLogfile(config):
    with workInTemporaryDirectory() as tempDir:
        dummyConfig = os.path.join(tempDir, 'config')
        logFile = os.path.join(tempDir, 'testlog.log')

        with open(logFile, 'w') as f:
            pass

        with open(dummyConfig, 'w') as f:
            f.write("""[global]
log_file = {0}""".format(logFile))

        config.set('global', 'config_file', dummyConfig)
        config.set('global', 'log_dir', tempDir)

        # First rotation
        config.readConfigFile(keepLog=False)
        print(os.listdir(tempDir))
        assert os.path.exists(os.path.join(tempDir, 'testlog.log.0'))

        # Second rotation
        config.readConfigFile(keepLog=False)
        print(os.listdir(tempDir))
        assert os.path.exists(os.path.join(tempDir, 'testlog.log.1'))
