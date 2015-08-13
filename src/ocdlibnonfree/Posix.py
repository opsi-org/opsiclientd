#! python
# -*- coding: utf-8 -*-

# Copyright (C) 2010-2015 uib GmbH
# http://www.uib.de/
# All rights reserved.
"""
Non-free Posix part of opsiclientd

:copyright: uib GmbH <info@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
"""

import os
import os.path
import sys
import time

import OPSI.System as System
from OPSI.Logger import Logger, LOG_NONE, LOG_NOTICE
from OPSI.Types import forceUnicode

from ocdlib.Opsiclientd import Opsiclientd

logger = Logger()


class OpsiclientdPosix(Opsiclientd):

    _PID_DIR = os.path.join("/var", "run", "opsiclientd")

    def __init__(self):
        super().__init__()

        if not os.path.exists(self._PID_DIR):
            os.mkdir(self._PID_DIR)

    def clearRebootRequest(self):
        rebootFile = os.path.join(self._PID_DIR, "reboot")
        try:
            os.remove(rebootFile)
        except OSError as err:
            logger.debug("Failed to remove reboot file {1!r}: {0}".format(err, rebootFile))

    def clearShutdownRequest(self):
        shutdownFile = os.path.join(self._PID_DIR, "shutdown")
        try:
            os.remove(shutdownFile)
        except OSError as err:
            logger.debug("Failed to remove shutdwn file {1!r}: {0}".format(err, shutdownFile))

    def isRebootRequested(self):
        rebootFile = os.path.join(self._PID_DIR, "reboot")
        return os.path.exists(rebootFile)

    def isShutdownRequested(self):
        shutdownFile = os.path.join(self._PID_DIR, "shutdown")
        return os.path.exists(shutdownFile)

    def rebootMachine(self):
        self._isRebootTriggered = True
        self.clearRebootRequest()
        System.reboot(wait=3)

    def shutdownMachine(self):
        self._isShutdownTriggered = True
        self.clearShutdownRequest()
        System.shutdown(wait=3)
