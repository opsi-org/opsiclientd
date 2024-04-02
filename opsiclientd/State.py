# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Application state.
"""

import json
import os
import threading
from pathlib import Path
from typing import Any

import psutil
from OPSI import System  # type: ignore[import]
from opsicommon.logging import get_logger
from opsicommon.types import forceBool, forceUnicode
from opsicommon.utils import Singleton

from opsiclientd.Config import OPSI_SETUP_USER_NAME, Config
from opsiclientd.SystemCheck import (
	RUNNING_ON_DARWIN,
	RUNNING_ON_LINUX,
	RUNNING_ON_WINDOWS,
)

config = Config()
logger = get_logger("opsiclientd")


class State(metaclass=Singleton):
	_initialized = False

	def __init__(self) -> None:
		if self._initialized:
			return
		self._initialized = True
		self._state: dict[str, Any] = {}
		self._stateFile: str | None = None
		self._stateLock = threading.Lock()

	def start(self) -> None:
		self._stateFile = config.get("global", "state_file")
		self._readStateFile()
		self.set("shutdown_cancel_counter", 0)

	def _readStateFile(self) -> None:
		with self._stateLock:
			try:
				assert self._stateFile
				if os.path.exists(self._stateFile):
					with open(self._stateFile, "r", encoding="utf8") as stateFile:
						jsonstr = stateFile.read()

					self._state = json.loads(jsonstr)
			except Exception as error:
				logger.error("Failed to read state file '%s': %s", self._stateFile, error)

	def _writeStateFile(self) -> None:
		with self._stateLock:
			try:
				assert self._stateFile
				jsonstr = json.dumps(self._state)
				if not os.path.exists(os.path.dirname(self._stateFile)):
					os.makedirs(os.path.dirname(self._stateFile))

				with open(self._stateFile, "w", encoding="utf8") as stateFile:
					stateFile.write(jsonstr)
			except Exception as error:
				logger.error("Failed to write state file '%s': %s", self._stateFile, error)

	def get(self, name: str, default: Any = None) -> Any:
		name = forceUnicode(name)
		if name == "user_logged_in":
			if RUNNING_ON_WINDOWS:
				for session in System.getActiveSessionInformation():
					if session["UserName"] != OPSI_SETUP_USER_NAME:
						return True
			elif RUNNING_ON_LINUX:
				for proc in psutil.process_iter():
					try:
						env = proc.environ()
						if env.get("DISPLAY") and proc.uids()[0] >= 1000:
							return True
					except psutil.AccessDenied:
						pass
			elif RUNNING_ON_DARWIN:
				if Path("/dev/console").owner() != "root":
					return True
			return False
		if name == "products_cached":
			return self._state.get("product_cache_service", {}).get("products_cached", default)
		if name == "config_cached":
			return self._state.get("config_cache_service", {}).get("config_cached", default)
		if "cancel_counter" in name:
			return self._state.get(name, 0)
		if name == "installation_pending":
			return forceBool(self._state.get("installation_pending", False))
		if name == "message_of_the_day":
			return self._state.get("message_of_the_day", default)
		try:
			return self._state[name]
		except KeyError:
			logger.warning("Unknown state name '%s', returning default '%s'", name, default)
			return default

	def set(self, name: str, value: Any) -> None:
		name = forceUnicode(name)
		logger.debug("Setting state '%s' to %s", name, value)
		self._state[name] = value
		self._writeStateFile()
