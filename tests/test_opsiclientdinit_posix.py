# -*- coding: utf-8 -*-

# Copyright 2015-2019 uib GmbH
# http://www.uib.de/
# All rights reserved.

from __future__ import absolute_import

import os

from .helper import workInTemporaryDirectory

import pytest

try:
	from opsiclientd.posix.main import main, write_pid_file
except ImportError as error:
	print("Failed to import: {0}".format(error))
	main = None


@pytest.mark.skipif(main is None, reason="Unable to find non-free modules.")
def testWritingPID():
	currentPID = os.getpid()

	with workInTemporaryDirectory() as tempDir:
		targetFile = os.path.join(tempDir, 'pidfile')
		write_pid_file(targetFile)

		with open(targetFile) as f:
			pid = int(f.read().strip())

		assert currentPID == pid


@pytest.mark.skipif(main is None, reason="Unable to find non-free modules.")
def testNotWritingPIDtoEmptyPath():
	with workInTemporaryDirectory() as tempDir:
		write_pid_file(None)
		assert not [e for e in os.listdir(tempDir)]

		write_pid_file("")
		assert not [e for e in os.listdir(tempDir)]
