# -*- coding: utf-8 -*-

# Copyright (C) 2010-2019 uib GmbH
# http://www.uib.de/
# All rights reserved.
"""
Non-free Posix part of opsiclientd

:copyright: uib GmbH <info@uib.de>
"""

import os
import os.path

import OPSI.System as System
from opsicommon.logging import logger

from opsiclientd.Opsiclientd import Opsiclientd

__all__ = ['OpsiclientdPosix']

class OpsiclientdPosix(Opsiclientd):

	_PID_DIR = os.path.join("/var", "run", "opsiclientd")

	def __init__(self):
		super(OpsiclientdPosix, self).__init__()

		if not os.path.exists(self._PID_DIR):
			os.makedirs(self._PID_DIR)

	def clearRebootRequest(self):
		rebootFile = os.path.join(self._PID_DIR, "reboot")
		if os.path.exists(rebootFile):
			try:
				os.remove(rebootFile)
			except OSError as err:
				logger.error("Failed to remove reboot file %s: %s", err, rebootFile)

	def clearShutdownRequest(self):
		shutdownFile = os.path.join(self._PID_DIR, "shutdown")
		if os.path.exists(shutdownFile):
			try:
				os.remove(shutdownFile)
			except OSError as err:
				logger.error("Failed to remove shutdown file %s: %s", err, shutdownFile)

	def isRebootRequested(self):
		rebootFile = os.path.join(self._PID_DIR, "reboot")
		return os.path.exists(rebootFile)

	def isShutdownRequested(self):
		shutdownFile = os.path.join(self._PID_DIR, "shutdown")
		return os.path.exists(shutdownFile)

