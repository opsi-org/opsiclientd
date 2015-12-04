#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2015 uib GmbH
# http://www.uib.de/
# All rights reserved.

import os
import unittest
from helper import workInTemporaryDirectory

import mock

try:
    from ocdlib.Posix import OpsiclientdInit
except ImportError as error:
    print("Failed to import: {0}".format(error))
    OpsiclientdInit = None


@unittest.skipIf(OpsiclientdInit is None, "Missing OpsiclientdInit")
class OpsiclientdRebootCoordinationTestCase(unittest.TestCase):
    """
    Testing the reboot behaviour on a POSIX machine.
    """
    def testWritingPID(self):
        currentPID = os.getpid()

        with workInTemporaryDirectory() as tempDir:
            targetFile = os.path.join(tempDir, 'pidfile')
            OpsiclientdInit.writePIDFile()

            with open(targetFile) as f:
                pid = int(f.read().strip())

            self.assertEquals(currentPID, pid)
