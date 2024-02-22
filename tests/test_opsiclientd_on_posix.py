# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
test_opsiclientd_on_posix
"""

import mock
import pytest

try:
	from opsiclientd.nonfree.Posix import OpsiclientdPosix

	error_message = ""
except ImportError as err:
	OpsiclientdPosix = None
	error_message = str(err)


@pytest.mark.skipif(OpsiclientdPosix is None, reason=error_message)
def test_requesting_reboot(tmpdir):
	with mock.patch("opsiclientd.nonfree.Posix.OpsiclientdPosix._PID_DIR", str(tmpdir)):
		ocd = OpsiclientdPosix()
		assert not ocd.isRebootRequested()
		rebootFile = tmpdir / "reboot"
		with open(rebootFile, "w", encoding="ascii"):
			pass
		ocd.clearRebootRequest()
		assert not ocd.isRebootRequested()


@pytest.mark.skipif(OpsiclientdPosix is None, reason=error_message)
def test_requesting_shutdown(tmpdir):
	with mock.patch("opsiclientd.nonfree.Posix.OpsiclientdPosix._PID_DIR", str(tmpdir)):
		ocd = OpsiclientdPosix()
		assert not ocd.isShutdownRequested()
		rebootFile = tmpdir / "shutdown"
		with open(rebootFile, "w", encoding="ascii"):
			pass

		ocd.clearShutdownRequest()
		assert not ocd.isShutdownRequested()
