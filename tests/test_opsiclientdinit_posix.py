# -*- coding: utf-8 -*-

# Copyright 2015-2019 uib GmbH
# http://www.uib.de/
# All rights reserved.

from __future__ import absolute_import

import os

from .helper import workInTemporaryDirectory

import pytest

try:
	from opsiclientd.Posix import OpsiclientdInitPosix
except ImportError as error:
	print("Failed to import: {0}".format(error))
	OpsiclientdInit = None


@pytest.mark.skipif(OpsiclientdInitPosix is None, reason="Unable to find non-free modules.")
def testWritingPID():
	currentPID = os.getpid()

	with workInTemporaryDirectory() as tempDir:
		targetFile = os.path.join(tempDir, 'pidfile')
		OpsiclientdInitPosix.writePIDFile(targetFile)

		with open(targetFile) as f:
			pid = int(f.read().strip())

		assert currentPID == pid


@pytest.mark.skipif(OpsiclientdInitPosix is None, reason="Unable to find non-free modules.")
def testNotWritingPIDtoEmptyPath():
	with workInTemporaryDirectory() as tempDir:
		OpsiclientdInitPosix.writePIDFile(None)
		assert not [e for e in os.listdir(tempDir)]

		OpsiclientdInitPosix.writePIDFile("")
		assert not [e for e in os.listdir(tempDir)]
