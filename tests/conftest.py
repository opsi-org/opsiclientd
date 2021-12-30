# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
conftest
"""

import sys
import urllib3
import platform
from _pytest.logging import LogCaptureHandler

import pytest

urllib3.disable_warnings()

def emit(*args, **kwargs) -> None:  # pylint: disable=unused-argument
	pass
LogCaptureHandler.emit = emit


def pytest_runtest_setup(item):
	supported_platforms = {"windows", "linux", "darwin"}.intersection(
		mark.name for mark in item.iter_markers()
	)
	plat = platform.system().lower()
	if supported_platforms and plat not in supported_platforms:
		pytest.skip(f"Cannot run on {plat}")
