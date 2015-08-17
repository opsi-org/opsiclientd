#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2015 uib GmbH
# http://www.uib.de/
# All rights reserved.

import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from functools import wraps

import mock

try:
    from ocdlibnonfree.Posix import Opsiclientd
except ImportError as error:
    print("Failed to import: {0}".format(error))
    Opsiclientd = None


@contextmanager
def workInTemporaryDirectory(tempDir=None):
    """
    Creates a temporary folder to work in. Deletes the folder afterwards.

    :param tempDir: use the given dir as temporary directory. Will not \
be deleted if given.
    """
    temporary_folder = tempDir or tempfile.mkdtemp()
    with cd(temporary_folder):
        yield temporary_folder

    if not tempDir and os.path.exists(temporary_folder):
        shutil.rmtree(temporary_folder)


@contextmanager
def cd(path):
    old_dir = os.getcwd()
    os.chdir(path)
    yield
    os.chdir(old_dir)


@unittest.skipIf(Opsiclientd is None, "Unable to find non-free modules.")
class OpsiclientdRebootCoordinationTestCase(unittest.TestCase):
    """
    Testing the reboot behaviour on a POSIX machine.
    """

    def test_requesting_reboot(self):
        with workInTemporaryDirectory() as tempDir:
            with mock.patch('ocdlibnonfree.Posix.Opsiclientd._PID_DIR', tempDir):
                ocd = Opsiclientd()

                self.assertFalse(ocd.isRebootRequested())

                rebootFile = os.path.join(tempDir, 'reboot')
                with open(rebootFile, 'w'):
                    pass

                ocd.clearRebootRequest()
                self.assertFalse(ocd.isRebootRequested())

    def test_requesting_shutdown(self):
        with workInTemporaryDirectory() as tempDir:
            with mock.patch('ocdlibnonfree.Posix.Opsiclientd._PID_DIR', tempDir):
                ocd = Opsiclientd()

                self.assertFalse(ocd.isShutdownRequested())

                rebootFile = os.path.join(tempDir, 'shutdown')
                with open(rebootFile, 'w'):
                    pass

                ocd.clearShutdownRequest()
                self.assertFalse(ocd.isShutdownRequested())
