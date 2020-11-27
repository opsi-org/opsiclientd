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
:copyright: uib GmbH <info@uib.de>
:license: GNU Affero General Public License version 3
"""

import os
import signal
import sys
import time
import subprocess
from signal import SIGHUP, SIGTERM, SIGINT

import opsicommon.logging
from opsicommon.logging import logger, logging_config, LOG_NONE

from opsiclientd import config, parser, init_logging
from opsiclientd.SystemCheck import RUNNING_ON_LINUX, RUNNING_ON_DARWIN

from opsiclientd.nonfree.Posix import OpsiclientdPosix


opsiclientd = None

def configure_iptables():
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

def signal_handler(signo, stackFrame):
	logger.debug("Received signal %s, stopping opsiclientd", signo)
	if opsiclientd:
		opsiclientd.stop()

def daemonize(stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
	"""
	Running as a daemon.
	"""
	# Fork to allow the shell to return and to call setsid
	try:
		if os.fork() > 0:
			raise SystemExit(0)  # Parent exit
	except OSError as e:
		raise RuntimeError(f"First fork failed: {e}")
	
	os.chdir("/")  # Do not hinder umounts
	os.umask(0)  # reset file mode mask
	os.setsid()  # Create a new session

	# Fork a second time to not remain session leader
	try:
		if os.fork() > 0:
			raise SystemExit(0)
	except OSError as e:
		raise RuntimeError(f"Second fork failed: {e}")
	
	logging_config(stderr_level=LOG_NONE)

	# Replacing file descriptors
	with open(stdin, 'rb', 0) as f:
		os.dup2(f.fileno(), sys.stdin.fileno())
	with open(stdout, 'rb', 0) as f:
		os.dup2(f.fileno(), sys.stdout.fileno())
	with open(stderr, 'rb', 0) as f:
		os.dup2(f.fileno(), sys.stderr.fileno())

def write_pid_file(path):
	if path:
		with open(path, 'w') as pidFile:
			pidFile.write(str(os.getpid()))

def main():
	global opsiclientd
	log_dir = "/var/log/opsi-client-agent"
	
	parser.add_argument(
		"--no-signal-handlers", "-t",
		dest="signalHandlers",
		action="store_false",
		default=True,
		help="Do not register signal handlers."
	)
	parser.add_argument(
		"--daemon", "-D",
		dest="daemon",
		action="store_true",
		default=False,
		help="Daemonize process."
	)
	parser.add_argument(
		"--pid-file",
		dest="pidFile",
		default=None,
		help="Write the PID into this file."
	)
	
	options = parser.parse_args()
	
	init_logging(log_dir=log_dir, stderr_level=options.logLevel, log_filter=options.logFilter)
	
	with opsicommon.logging.log_context({'instance', 'opsiclientd'}):
		if options.signalHandlers:
			logger.debug("Registering signal handlers")
			signal.signal(SIGHUP, signal.SIG_IGN)  # ignore SIGHUP
			signal.signal(SIGTERM, signal_handler)
			signal.signal(SIGINT, signal_handler)  # aka. KeyboardInterrupt
		else:
			logger.notice("Not registering any signal handlers!")

		if options.daemon:
			logging_config(stderr_level=LOG_NONE)
			daemonize()

		write_pid_file(options.pidFile)
		if RUNNING_ON_LINUX:
			try:
				configure_iptables()
			except Exception as e:
				logger.error("Failed to configure iptabels: %s", e)
		
		logger.debug("Starting opsiclientd...")
		opsiclientd = OpsiclientdPosix()
		opsiclientd.start()

		try:
			while opsiclientd.is_alive():
				time.sleep(1)

			logger.debug("Stopping opsiclientd...")
			opsiclientd.join(60)
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
					logger.debug("Removing pid file failed: %s", oserr)

	
