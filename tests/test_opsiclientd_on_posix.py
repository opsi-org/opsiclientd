# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

from .helper import workInTemporaryDirectory
import os
import mock
import pytest
try:
	from opsiclientd.nonfree.Posix import OpsiclientdPosix
	errorMessage = ""
except ImportError as error:
	print("Failed to import: {0}".format(error))
	errorMessage = str(error)
	OpsiclientdPosix = None

@pytest.mark.skipif(OpsiclientdPosix is None, reason="Unable to find non-free modules: %s" % errorMessage)
def test_requesting_reboot():
	with workInTemporaryDirectory() as tempDir:
		with mock.patch('opsiclientd.nonfree.Posix.OpsiclientdPosix._PID_DIR', tempDir):
			ocd = OpsiclientdPosix()
			assert not ocd.isRebootRequested()
			rebootFile = os.path.join(tempDir, 'reboot')
			with open(rebootFile, 'w'):
				pass
			ocd.clearRebootRequest()
			assert not ocd.isRebootRequested()

@pytest.mark.skipif(OpsiclientdPosix is None, reason="Unable to find non-free modules: %s" % errorMessage)
def test_requesting_shutdown():
	with workInTemporaryDirectory() as tempDir:
		with mock.patch('opsiclientd.nonfree.Posix.OpsiclientdPosix._PID_DIR', tempDir):
			ocd = OpsiclientdPosix()
			assert not ocd.isShutdownRequested()
			rebootFile = os.path.join(tempDir, 'shutdown')
			with open(rebootFile, 'w'):
				pass

			ocd.clearShutdownRequest()
			assert not ocd.isShutdownRequested()
