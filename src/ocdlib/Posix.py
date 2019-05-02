#! python
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
Functionality to work on POSIX-conform systems.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:license: GNU Affero General Public License version 3
"""

import argparse
import os
import signal
import sys
import time
from signal import SIGHUP, SIGTERM, SIGINT

from OPSI.Logger import Logger, LOG_NONE, LOG_NOTICE, LOG_WARNING
from OPSI.Types import forceUnicode

from ocdlib import __version__
from ocdlib.Opsiclientd import Opsiclientd

__all__ = ('OpsiclientdInit', )

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
		parser.add_argument("--log-level", "-l", dest="logLevel", type=int,
							choices=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
							default=LOG_NOTICE,
							help="Set the log-level.")
		parser.add_argument('--no-signal-handlers', '-t', dest="signalHandlers",
							action="store_false", default=True,
							help="Do not register signal handlers.")
		parser.add_argument("--daemon", "-D", dest="daemon",
							action="store_true", default=False,
							help="Daemonize process.")
		parser.add_argument("--pid-file", dest="pidFile", default=None,
							help="Write the PID into this file.")

		options = parser.parse_args()

		logger.setConsoleLevel(options.logLevel)

		if options.signalHandlers:
			logger.debug("Registering signal handlers")
			signal.signal(SIGHUP, signal.SIG_IGN)  # ignore SIGHUP
			signal.signal(SIGTERM, self.signalHandler)
			signal.signal(SIGINT, self.signalHandler)  # aka. KeyboardInterrupt
		else:
			logger.notice(u'Not registering any signal handlers!')

		if options.daemon:
			logger.setConsoleLevel(LOG_NONE)
			self.daemonize()

		self.writePIDFile(options.pidFile)

		logger.debug("Starting opsiclientd...")
		self._opsiclientd = OpsiclientdPosix()
		self._opsiclientd.start()

		try:
			while self._opsiclientd.is_alive():
				time.sleep(1)

			logger.debug("Stopping opsiclientd...")
			self._opsiclientd.join(60)
			logger.debug("Stopped.")
		except Exception as e:
			logger.logException(e)
		finally:
			if options.pidFile:
				logger.debug("Removing PID file...")
				try:
					os.remove(options.pidFile)
					logger.debug("PID file removed.")
				except OSError as oserr:
					logger.debug("Removing pid file failed: {0}".format(oserr))


	def signalHandler(self, signo, stackFrame):
		logger.debug('Received signal {0}. Stopping opsiclientd.'.format(signo))
		self._opsiclientd.stop()

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

	@staticmethod
	def writePIDFile(path):
		if path:
			with open(path, 'w') as pidFile:
				pidFile.write(str(os.getpid()))
