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


import getopt
import os
import sys
import time
from signal import *

from OPSI.Logger import LOG_NONE, LOG_NOTICE, Logger
from OPSI.Types import forceUnicode

from ocdlib import __version__
from ocdlib.Opsiclientd import Opsiclientd

__all__ = ('OpsiclientdInit', )

logger = Logger()


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                         OPSICLIENTD POSIX                                         -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdPosix(Opsiclientd):
	def __init__(self):
		Opsiclientd.__init__(self)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# -                                       OPSICLIENTD POSIX INIT                                      -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
class OpsiclientdInit(object):
	def __init__(self):
		logger.debug(u"OpsiclientdPosixInit")
		argv = sys.argv[1:]

		# Call signalHandler on signal SIGHUP, SIGTERM, SIGINT
		signal(SIGHUP,  self.signalHandler)
		signal(SIGTERM, self.signalHandler)
		signal(SIGINT,  self.signalHandler)

		# Process command line arguments
		try:
			(opts, args) = getopt.getopt(argv, "vDl:")

		except getopt.GetoptError:
			self.usage()
			sys.exit(1)

		daemon = False
		logLevel = LOG_NOTICE
		for (opt, arg) in opts:
			if opt == "-v":
				print u"opsiclientd version %s" % __version__
				sys.exit(0)
			elif opt == "-D":
				daemon = True
			elif opt == "-l":
				logLevel = int(arg)

		if daemon:
			logger.setConsoleLevel(LOG_NONE)
			self.daemonize()
		else:
			logger.setConsoleLevel(logLevel)

		# Start opsiclientd
		self._opsiclientd = OpsiclientdPosix()
		self._opsiclientd.start()
		#self._opsiclientd.join()
		while self._opsiclientd.isRunning():
			time.sleep(1)

	def signalHandler(self, signo, stackFrame):
		if (signo == SIGHUP):
			return
		if (signo == SIGTERM or signo == SIGINT):
			self._opsiclientd.stop()

	def usage(self):
		print u"\nUsage: %s [-v] [-D]" % os.path.basename(sys.argv[0])
		print u"Options:"
		print u"  -v    Show version information and exit"
		print u"  -D    Causes the server to operate as a daemon"
		print u"  -l    Set log level (default: 4)"
		print u"        0=nothing, 1=critical, 2=error, 3=warning, 4=notice, 5=info, 6=debug, 7=debug2, 9=confidential"
		print u""

	def daemonize(self):
		return
		# Fork to allow the shell to return and to call setsid
		try:
			pid = os.fork()
			if (pid > 0):
				# Parent exits
				sys.exit(0)
		except OSError, e:
			raise Exception(u"First fork failed: %e" % forceUnicode(e))

		# Do not hinder umounts
		os.chdir("/")
		# Create a new session
		os.setsid()

		# Fork a second time to not remain session leader
		try:
			pid = os.fork()
			if (pid > 0):
				sys.exit(0)
		except OSError, e:
			raise Exception(u"Second fork failed: %e" % forceUnicode(e))

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
