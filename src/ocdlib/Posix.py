#! python
# -*- coding: utf-8 -*-
"""
ocdlib.Posix

opsiclientd is part of the desktop management solution opsi
(open pc server integration) http://www.opsi.org

Copyright (C) 2010-2015 uib GmbH

http://www.uib.de/

All rights reserved.

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License version 2 as
published by the Free Software Foundation.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

@copyright:	uib GmbH <info@uib.de>
@author: Jan Schneider <j.schneider@uib.de>
@author: Niko Wenselowski <n.wenselowski@uib.de>
@license: GNU General Public License version 2
"""
from __future__ import unicode_literals

import os
import sys
import time
from signal import signal, SIGHUP, SIGTERM, SIGINT

from OPSI.Logger import Logger, LOG_NONE, LOG_NOTICE, LOG_WARNING
from OPSI.Types import forceUnicode

from ocdlib import __version__
from ocdlib.Opsiclientd import Opsiclientd

try:
	import argparse
except ImportError:
	from OPSI.Util import argparse

logger = Logger()


try:
    from ocdlibnonfree.Posix import OpsiclientdPosix
except ImportError:
    logger.setConsoleLevel(LOG_WARNING)
    logger.warning("Import of OpsiclientdPosix failed.")

    class OpsiclientdPosix(Opsiclientd):
	    pass


class OpsiclientdInit(object):
	def __init__(self):
		logger.debug(u"OpsiclientdPosixInit")

		parser = argparse.ArgumentParser()
		parser.add_argument("-v", action='version', version=__version__)
		parser.add_argument("-l", "--log-level", dest="logLevel",
							default=LOG_NOTICE,
							help="Set the log-level.")
		parser.add_argument("-t", "--test-mode", dest="testMode",
							action="store_true", default=False,
							help="Testmode: Do no register signal handlers.")
		parser.add_argument("-D", "--daemon", dest="daemon",
							action="store_true", default=False,
							help="Daemonize process.")

		options = parser.parse_args()

		if not options.testMode:
			# Call signalHandler on signal SIGHUP, SIGTERM, SIGINT
			signal(SIGHUP, self.signalHandler)
			signal(SIGTERM, self.signalHandler)
			signal(SIGINT, self.signalHandler)
		else:
			logger.notice(u'Running in test mode!')

		if options.daemon:
			logger.setConsoleLevel(LOG_NONE)
			self.daemonize()
		else:
			logger.setConsoleLevel(options.logLevel)

		# Start opsiclientd
		self._opsiclientd = OpsiclientdPosix()
		self._opsiclientd.start()
		while self._opsiclientd.isRunning():
			time.sleep(1)

	def signalHandler(self, signo, stackFrame):
		if signo == SIGHUP:
			return
		elif signo == SIGTERM or signo == SIGINT:
			self._opsiclientd.stop()

	def daemonize(self):
		"""
		Running as a daemon.
		"""
		# Fork to allow the shell to return and to call setsid
		try:
			pid = os.fork()
			if (pid > 0):
				# Parent exits
				sys.exit(0)
		except OSError as err:
			raise Exception(u"First fork failed: %e" % forceUnicode(err))

		# Do not hinder umounts
		os.chdir("/")
		# Create a new session
		os.setsid()

		# Fork a second time to not remain session leader
		try:
			pid = os.fork()
			if (pid > 0):
				sys.exit(0)
		except OSError as oserr:
			raise Exception(u"Second fork failed: {0}".format(oserr))

		logger.setConsoleLevel(LOG_NONE)

		# Close standard output and standard error.
		os.close(0)
		os.close(1)
		os.close(2)

		# Open standard input (0)
		if (hasattr(os, "devnull")):
			os.open(os.devnull, os.O_RDWR)
		else:
			os.open("/dev/null", os.O_RDWR)

		# Duplicate standard input to standard output and standard error.
		os.dup2(0, 1)
		os.dup2(0, 2)
		sys.stdout = logger.getStdout()
		sys.stderr = logger.getStderr()
