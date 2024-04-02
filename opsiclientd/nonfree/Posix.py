# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
"""
Non-free Posix part of opsiclientd
"""

import os
import os.path

from opsicommon.logging import logger

from opsiclientd.Opsiclientd import Opsiclientd

__all__ = ["OpsiclientdPosix"]


class OpsiclientdPosix(Opsiclientd):
	_PID_DIR = os.path.join("/var", "run", "opsiclientd")

	def __init__(self):
		super().__init__()

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

	def loginUser(self, username, password):
		raise NotImplementedError("Not implemented on posix")
