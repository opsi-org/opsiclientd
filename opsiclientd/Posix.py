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

import os
import signal
import sys
import time
import subprocess
from signal import SIGHUP, SIGTERM, SIGINT

import opsicommon.logging
from opsicommon.logging import logger, LOG_NONE, LOG_NOTICE, LOG_WARNING 
from OPSI.Types import forceUnicode

from opsiclientd.Config import Config
from opsiclientd.Opsiclientd import OpsiclientdInit

#logger = Logger()
config = Config()

try:
	from opsiclientd.nonfree.Posix import OpsiclientdPosix
except ImportError as exc:
	raise


class OpsiclientdPosixInit(OpsiclientdInit):
	def __init__(self):
		try:
			super().__init__()
			logger.debug(u"OpsiclientdPosixInit")

			self.parser.add_argument('--no-signal-handlers', '-t', dest="signalHandlers",
								action="store_false", default=True,
								help="Do not register signal handlers.")
			self.parser.add_argument("--daemon", "-D", dest="daemon",
								action="store_true", default=False,
								help="Daemonize process.")
			self.parser.add_argument("--pid-file", dest="pidFile", default=None,
								help="Write the PID into this file.")
			
			options = self.parser.parse_args()

			self.init_logging(stderr_level=options.logLevel, log_filter=options.logFilter)

			with opsicommon.logging.log_context({'instance', 'opsiclientd'}):

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
				self.configure_iptables()

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
		except Exception as exc:
			logger.critical(exc, exc_info=True)

	def configure_iptables(self):
		logger.notice("Configure iptables")
		port = config.get('control_server', 'port')
		cmds = []
		if os.path.exists("/usr/bin/firewall-cmd"):
			# openSUSE Leap
			cmds.append(["/usr/bin/firewall-cmd", f"--add-port={port}/tcp", "--zone", "public"])
		else:
			for iptables in ("iptables", "ip6tables"):
				cmds.append([iptables, "-A", "INPUT", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"])
		
		for cmd in cmds:
			logger.info("Running command: %s", str(cmd))
			subprocess.call(cmd)

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

	@staticmethod
	def writePIDFile(path):
		if path:
			with open(path, 'w') as pidFile:
				pidFile.write(str(os.getpid()))
