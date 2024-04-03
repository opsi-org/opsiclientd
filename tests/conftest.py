# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
conftest
"""

import platform
import warnings
from typing import Any

import psutil
import pytest
import urllib3
from _pytest.config import Config
from _pytest.logging import LogCaptureHandler
from _pytest.nodes import Item


# Disable pytest log capture
def emit(*args: Any, **kwargs: Any) -> None:
	pass


LogCaptureHandler.emit = emit  # type: ignore[method-assign]


@pytest.hookimpl()
def pytest_configure(config: Config) -> None:
	config.addinivalue_line("markers", "docker_linux: mark test to run only on linux in docker")
	config.addinivalue_line("markers", "opsiclientd_running: mark test to run only if an opsiclientd instance is running")
	config.addinivalue_line("markers", "windows: mark test to run only on windows")
	config.addinivalue_line("markers", "linux: mark test to run only on linux")
	config.addinivalue_line("markers", "darwin: mark test to run only on darwin")
	config.addinivalue_line("markers", "posix: mark test to run only on posix")


def running_in_docker() -> bool:
	try:
		with open("/proc/2/stat", encoding="utf-8", errors="replace") as file:
			return "kthreadd" not in file.read()
	except FileNotFoundError:
		return True
	except Exception:
		pass
	return False


def opsiclient_running() -> bool:
	for proc in psutil.process_iter():
		if proc.name() == "opsiclientd" or (
			proc.name() in ("python", "python3") and ("opsiclientd" in proc.cmdline() or "opsiclientd.__main__" in " ".join(proc.cmdline()))
		):
			return True
	return False


PLATFORM = platform.system().lower()
RUNNING_IN_DOCKER = running_in_docker()
OPSICLIENTD_RUNNING = RUNNING_IN_DOCKER and opsiclient_running()


def pytest_runtest_setup(item: Item) -> None:
	supported_platforms = []
	for marker in item.iter_markers():
		if marker == "docker_linux" and not RUNNING_IN_DOCKER:
			pytest.skip("Must run in docker")
		if marker.name == "opsiclientd_running" and not OPSICLIENTD_RUNNING:
			pytest.skip("No opsiclientd test instance running")
			return
		if marker.name in ("windows", "linux", "darwin", "posix"):
			if marker.name == "posix":
				supported_platforms.extend(["linux", "darwin"])
			else:
				supported_platforms.append(marker.name)

	if supported_platforms and PLATFORM not in supported_platforms:
		pytest.skip(f"Cannot run on {PLATFORM}")


@pytest.fixture(autouse=True)
def disable_insecure_request_warning() -> None:
	warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
