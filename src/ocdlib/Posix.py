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

import os
import sys
import time
from signal import signal, SIGHUP, SIGTERM, SIGINT

from OPSI.Logger import Logger, LOG_NONE, LOG_NOTICE, LOG_WARNING
from OPSI.Types import forceUnicode

from ocdlib import __version__

try:
	import argparse
except ImportError:
	from OPSI.Util import argparse

logger = Logger()


try:
    from ocdlibnonfree.Posix import OpsiclientdPosix
except ImportError:
    logger.setConsoleLevel(LOG_WARNING)
    logger.critical("Import of OpsiclientdPosix failed.")
    raise


class OpsiclientdInit(object):
	def __init__(self):
		logger.debug(u"OpsiclientdPosixInit")

		parser = argparse.ArgumentParser()
		parser.add_argument("--version", "-V", action='version', version=__version__)
		parser.add_argument("-l", "--log-level", dest="logLevel",
							default=LOG_NOTICE,
							help="Set the log-level.")
		parser.add_argument('-t', '--no-signal-handlers', dest="signalHandlers",
							action="store_false", default=True,
							help="Do no register signal handlers.")
		parser.add_argument("-D", "--daemon", dest="daemon",
							action="store_true", default=False,
							help="Daemonize process.")

		options = parser.parse_args()

		logger.setConsoleLevel(options.logLevel)

		if options.signalHandlers:
			# Call signalHandler on signal SIGHUP, SIGTERM, SIGINT
			signal(SIGHUP, self.signalHandler)
			signal(SIGTERM, self.signalHandler)
			signal(SIGINT, self.signalHandler)
		else:
			logger.notice(u'Not registering any signal handlers!')

		if options.daemon:
			logger.setConsoleLevel(LOG_NONE)
			self.daemonize()

		logger.debug("Starting opsiclientd...")
		self._opsiclientd = OpsiclientdPosix()
		self._opsiclientd.start()
		while self._opsiclientd.isRunning():
			time.sleep(0.1)

	def signalHandler(self, signo, stackFrame):
		if signo == SIGHUP:
			return
		elif signo in (SIGTERM, SIGINT):
			logger.info('Received singal {0}. Stopping opsiclientd.')
			self._opsiclientd.stop()
			# raise SystemExit(1)

	def daemonize(self, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
		"""
		Running as a daemon.
		"""
		# Fork to allow the shell to return and to call setsid
		try:
			if os.fork() > 0:
				raise SystemExit(0)  # Parent exit
		except OSError as err:
			raise RuntimeError(u"First fork failed: %e" % forceUnicode(err))

		os.chdir("/")  # Do not hinder umounts
		os.umask(0)  # reset file mode mask
		os.setsid()  # Create a new session

		# Fork a second time to not remain session leader
		try:
			if os.fork() > 0:
				raise SystemExit(0)
		except OSError as oserr:
			raise RuntimeError(u"Second fork failed: {0}".format(oserr))

		logger.setConsoleLevel(LOG_NONE)

		# Replacing file descriptors
		with open(stdin, 'rb', 0) as f:
			os.dup2(f.fileno(), sys.stdin.fileno())
		with open(stdout, 'rb', 0) as f:
			os.dup2(f.fileno(), sys.stdout.fileno())
		with open(stderr, 'rb', 0) as f:
			os.dup2(f.fileno(), sys.stderr.fileno())

		# Replacing stdout & stderr with our variants
		sys.stdout = logger.getStdout()
		sys.stderr = logger.getStderr()
