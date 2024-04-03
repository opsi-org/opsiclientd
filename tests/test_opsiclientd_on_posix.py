# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
test_opsiclientd_on_posix
"""

from pathlib import Path

import mock
import pytest

try:
	from opsiclientd.nonfree.Posix import OpsiclientdPosix

	error_message = ""
except ImportError as err:
	OpsiclientdPosix = None  # type: ignore
	error_message = str(err)


@pytest.mark.skipif(OpsiclientdPosix is None, reason=error_message)
def test_requesting_reboot(tmp_path: Path) -> None:
	with mock.patch("opsiclientd.nonfree.Posix.OpsiclientdPosix._PID_DIR", str(tmp_path)):
		ocd = OpsiclientdPosix()
		assert not ocd.isRebootRequested()
		rebootFile = tmp_path / "reboot"
		with open(rebootFile, "w", encoding="ascii"):
			pass
		ocd.clearRebootRequest()
		assert not ocd.isRebootRequested()


@pytest.mark.skipif(OpsiclientdPosix is None, reason=error_message)
def test_requesting_shutdown(tmp_path: Path) -> None:
	with mock.patch("opsiclientd.nonfree.Posix.OpsiclientdPosix._PID_DIR", str(tmp_path)):
		ocd = OpsiclientdPosix()
		assert not ocd.isShutdownRequested()
		rebootFile = tmp_path / "shutdown"
		with open(rebootFile, "w", encoding="ascii"):
			pass

		ocd.clearShutdownRequest()
		assert not ocd.isShutdownRequested()
