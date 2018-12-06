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

from OPSI.Logger import Logger
from OPSI.Types import forceBool, forceUnicode
from OPSI import System

from ocdlib.Config import Config
from ocdlib.OpsiService import isConfigServiceReachable

logger = Logger()
config = Config()


class StateImplementation(object):
	def __init__(self):
		self._state = {}
		self._stateFile = config.get('global', 'state_file')
		self._winApiBugCommand = os.path.join(config.get('global', 'base_dir'), 'utilities\sessionhelper\getActiveSessionIds.exe')
		self._stateLock = threading.Lock()
		self._readStateFile()
		self.set('shutdown_cancel_counter', 0)

	def _readStateFile(self):
		with self._stateLock:
			try:
				if os.path.exists(self._stateFile):
					with codecs.open(self._stateFile, 'r', 'utf8') as stateFile:
						jsonstr = stateFile.read()

					self._state = json.loads(jsonstr)
			except Exception as error:
				logger.error(u"Failed to read state file '%s': %s" % (self._stateFile, error))

	def _writeStateFile(self):
		with self._stateLock:
			try:
				jsonstr = json.dumps(self._state)
				if not os.path.exists(os.path.dirname(self._stateFile)):
					os.makedirs(os.path.dirname(self._stateFile))

				with codecs.open(self._stateFile, 'w', 'utf8') as stateFile:
					stateFile.write(jsonstr)
			except Exception as error:
				logger.error(u"Failed to write state file '%s': %s" % (self._stateFile, error))

	def get(self, name, default=None):
		name = forceUnicode(name)
		if name == 'user_logged_in':
			return bool(System.getActiveSessionIds(self._winApiBugCommand))
		elif name == 'configserver_reachable':
			return isConfigServiceReachable(timeout=15)
		elif name == 'products_cached':
			return self._state.get('product_cache_service', {}).get('products_cached', default)
		elif name == 'config_cached':
			return self._state.get('config_cache_service', {}).get('config_cached', default)
		elif "cancel_counter" in name:
			return self._state.get(name, 0)
		elif name == 'installation_pending':
			return forceBool(self._state.get('installation_pending', False))

		try:
			return self._state[name]
		except KeyError:
			logger.warning(u"Unknown state name {0!r}, returning default {1!r}", name, default)
			return default

	def set(self, name, value):
		name = forceUnicode(name)
		logger.debug(u"Setting state '%s' to %s" % (name, value))
		self._state[name] = value
		self._writeStateFile()


class State(StateImplementation):
	# Storage for the instance reference
	__instance = None

	def __init__(self):
		""" Create singleton instance """

		# Check whether we already have an instance
		if State.__instance is None:
			# Create and remember instance
			State.__instance = StateImplementation()

		# Store instance reference as the only member in the handle
		self.__dict__['_State__instance'] = State.__instance

	def __getattr__(self, attr):
		""" Delegate access to implementation """
		return getattr(self.__instance, attr)

	def __setattr__(self, attr, value):
		""" Delegate access to implementation """
		return setattr(self.__instance, attr, value)
