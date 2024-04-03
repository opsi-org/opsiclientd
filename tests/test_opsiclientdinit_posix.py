# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
test_opsiclientdinit_posix
"""

import os
from pathlib import Path

import pytest

try:
	from opsiclientd.posix.main import main, write_pid_file

	error_message = ""
except ImportError as err:
	main = None  # type: ignore[assignment]
	error_message = str(err)


@pytest.mark.skipif(main is None, reason="Unable to find non-free modules.")
def testWritingPID(tmp_path: Path) -> None:
	currentPID = os.getpid()
	targetFile = str(tmp_path / "pidfile")
	write_pid_file(targetFile)
	with open(targetFile, encoding="ascii") as file:
		pid = int(file.read().strip())
	assert currentPID == pid


@pytest.mark.skipif(main is None, reason="Unable to find non-free modules.")
def testNotWritingPIDtoEmptyPath(tmp_path: Path) -> None:
	write_pid_file(None)
	assert not list(os.listdir(tmp_path))
	write_pid_file("")
	assert not list(os.listdir(tmp_path))
