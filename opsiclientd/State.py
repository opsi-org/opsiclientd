# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2018 uib GmbH <info@uib.de>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Application state.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:license: GNU Affero General Public License version 3
"""

import os
import json
import codecs
import threading
import psutil

from opsicommon.utils import Singleton
from opsicommon.logging import logger
from OPSI.Types import forceBool, forceUnicode
from OPSI import System

from opsiclientd.Config import Config
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS, RUNNING_ON_DARWIN, RUNNING_ON_LINUX

config = Config()

class State(metaclass=Singleton):
	def __init__(self):
		self._state = {}
		self._stateFile = None
		self._stateLock = threading.Lock()

	def start(self):
		self._stateFile = config.get('global', 'state_file')
		self._readStateFile()
		self.set('shutdown_cancel_counter', 0)

	def _readStateFile(self):
		with self._stateLock:
			try:
				if os.path.exists(self._stateFile):
					with codecs.open(self._stateFile, 'r', 'utf8') as stateFile:
						jsonstr = stateFile.read()

					self._state = json.loads(jsonstr)
			except Exception as error: # pylint: disable=broad-except
				logger.error("Failed to read state file '%s': %s", self._stateFile, error)

	def _writeStateFile(self):
		with self._stateLock:
			try:
				jsonstr = json.dumps(self._state)
				if not os.path.exists(os.path.dirname(self._stateFile)):
					os.makedirs(os.path.dirname(self._stateFile))

				with codecs.open(self._stateFile, 'w', 'utf8') as stateFile:
					stateFile.write(jsonstr)
			except Exception as error: # pylint: disable=broad-except
				logger.error("Failed to write state file '%s': %s", self._stateFile, error)

	def get(self, name, default=None): # pylint: disable=too-many-return-statements,too-many-branches
		name = forceUnicode(name)
		if name == 'user_logged_in':
			if RUNNING_ON_WINDOWS:
				return bool(System.getActiveSessionIds())
			if RUNNING_ON_LINUX:
				for proc in psutil.process_iter():
					try:
						env = proc.environ()
						if env.get("DISPLAY") and proc.uids()[0] >= 1000:
							return True
					except psutil.AccessDenied:
						pass
				return False
			if RUNNING_ON_DARWIN:
				# TODO
				return True
			return False
		if name == 'products_cached':
			return self._state.get('product_cache_service', {}).get('products_cached', default)
		if name == 'config_cached':
			return self._state.get('config_cache_service', {}).get('config_cached', default)
		if "cancel_counter" in name:
			return self._state.get(name, 0)
		if name == 'installation_pending':
			return forceBool(self._state.get('installation_pending', False))

		try:
			return self._state[name]
		except KeyError:
			logger.warning("Unknown state name '%s', returning default '%s'", name, default)
			return default

	def set(self, name, value):
		name = forceUnicode(name)
		logger.debug("Setting state '%s' to %s", name, value)
		self._state[name] = value
		self._writeStateFile()
