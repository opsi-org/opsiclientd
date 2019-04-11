#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2015-2019 uib GmbH
# http://www.uib.de/
# All rights reserved.

import os
from helper import workInTemporaryDirectory

import pytest

try:
    from ocdlib.Posix import OpsiclientdInit
except ImportError as error:
    print("Failed to import: {0}".format(error))
    OpsiclientdInit = None


@pytest.mark.skipif(OpsiclientdInit is None, reason="Unable to find non-free modules.")
def testWritingPID(self):
    currentPID = os.getpid()

    with workInTemporaryDirectory() as tempDir:
        targetFile = os.path.join(tempDir, 'pidfile')
        OpsiclientdInit.writePIDFile(targetFile)

        with open(targetFile) as f:
            pid = int(f.read().strip())

        assert currentPID == pid


@pytest.mark.skipif(OpsiclientdInit is None, reason="Unable to find non-free modules.")
def testNotWritingPIDtoEmptyPath(self):
    with workInTemporaryDirectory() as tempDir:
        OpsiclientdInit.writePIDFile(None)
        assert not [e for e in os.listdir(tempDir)]

        OpsiclientdInit.writePIDFile("")
        assert not [e for e in os.listdir(tempDir)]
