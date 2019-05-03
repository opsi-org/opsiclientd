#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2015-2019 uib GmbH
# http://www.uib.de/
# All rights reserved.


from helper import workInTemporaryDirectory

import os
import mock

import pytest

try:
    from ocdlibnonfree.Posix import OpsiclientdPosix
except ImportError as error:
    print("Failed to import: {0}".format(error))
    OpsiclientdPosix = None


@pytest.mark.skipif(OpsiclientdPosix is None, reason="Unable to find non-free modules.")
def test_requesting_reboot():
    with workInTemporaryDirectory() as tempDir:
        with mock.patch('ocdlibnonfree.Posix.OpsiclientdPosix._PID_DIR', tempDir):
            ocd = OpsiclientdPosix()

            assert not ocd.isRebootRequested()

            rebootFile = os.path.join(tempDir, 'reboot')
            with open(rebootFile, 'w'):
                pass

            ocd.clearRebootRequest()
            assert not ocd.isRebootRequested()


@pytest.mark.skipif(OpsiclientdPosix is None, reason="Unable to find non-free modules.")
def test_requesting_shutdown():
    with workInTemporaryDirectory() as tempDir:
        with mock.patch('ocdlibnonfree.Posix.OpsiclientdPosix._PID_DIR', tempDir):
            ocd = OpsiclientdPosix()

            assert not ocd.isShutdownRequested()

            rebootFile = os.path.join(tempDir, 'shutdown')
            with open(rebootFile, 'w'):
                pass

            ocd.clearShutdownRequest()
            assert not ocd.isShutdownRequested()
