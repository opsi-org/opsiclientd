#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2015 uib GmbH
# http://www.uib.de/
# All rights reserved.


from helper import workInTemporaryDirectory

import os
import unittest

import mock

try:
    from ocdlibnonfree.Posix import Opsiclientd
except ImportError as error:
    print("Failed to import: {0}".format(error))
    Opsiclientd = None


@unittest.skipIf(Opsiclientd is None, "Unable to find non-free modules.")
class OpsiclientdRebootCoordinationTestCase(unittest.TestCase):
    """
    Testing the reboot behaviour on a POSIX machine.
    """

    def test_requesting_reboot(self):
        with workInTemporaryDirectory() as tempDir:
            with mock.patch('ocdlibnonfree.Posix.OpsiclientdPosix._PID_DIR', tempDir):
                ocd = Opsiclientd()

                self.assertFalse(ocd.isRebootRequested())

                rebootFile = os.path.join(tempDir, 'reboot')
                with open(rebootFile, 'w'):
                    pass

                ocd.clearRebootRequest()
                self.assertFalse(ocd.isRebootRequested())

    def test_requesting_shutdown(self):
        with workInTemporaryDirectory() as tempDir:
            with mock.patch('ocdlibnonfree.Posix.OpsiclientdPosix._PID_DIR', tempDir):
                ocd = Opsiclientd()

                self.assertFalse(ocd.isShutdownRequested())

                rebootFile = os.path.join(tempDir, 'shutdown')
                with open(rebootFile, 'w'):
                    pass

                ocd.clearShutdownRequest()
                self.assertFalse(ocd.isShutdownRequested())
