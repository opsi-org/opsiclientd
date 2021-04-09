# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0

from sys import exc_info
import os
import signal
import sys
import time
import subprocess
from signal import SIGHUP, SIGTERM, SIGINT

import opsicommon.logging
from opsicommon.logging import logger, logging_config, LOG_NONE

from opsiclientd import config, parser, init_logging
from opsiclientd.SystemCheck import RUNNING_ON_LINUX, RUNNING_ON_MACOS

from opsiclientd.nonfree.Posix import OpsiclientdPosix


opsiclientd = None # pylint: disable=invalid-name

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

def configure_macos_firewall():
	logger.notice("Configure MacOS firewall")
	cmds = []

	for path in ("/usr/local/bin/opsiclientd", "/usr/local/lib/opsiclientd/opsiclientd"):
		cmds.append(["/usr/libexec/ApplicationFirewall/socketfilterfw", "--add" , path])
		cmds.append(["/usr/libexec/ApplicationFirewall/socketfilterfw", "--unblockapp" , path])

	for cmd in cmds:
		logger.info("Running command: %s", str(cmd))
		subprocess.call(cmd)

def signal_handler(signo, stackFrame): # pylint: disable=unused-argument
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
	except OSError as err:
		raise RuntimeError(f"First fork failed: {err}") from err

	os.chdir("/")  # Do not hinder umounts
	os.umask(0)  # reset file mode mask
	os.setsid()  # Create a new session

	# Fork a second time to not remain session leader
	try:
		if os.fork() > 0:
			raise SystemExit(0)
	except OSError as err:
		raise RuntimeError(f"Second fork failed: {err}") from err

	logging_config(stderr_level=LOG_NONE)

	# Replacing file descriptors
	with open(stdin, 'rb', 0) as file:
		os.dup2(file.fileno(), sys.stdin.fileno())
	with open(stdout, 'rb', 0) as file:
		os.dup2(file.fileno(), sys.stdout.fileno())
	with open(stderr, 'rb', 0) as file:
		os.dup2(file.fileno(), sys.stderr.fileno())

def write_pid_file(path):
	if path:
		with open(path, 'w') as pidFile:
			pidFile.write(str(os.getpid()))

def main():
	global opsiclientd # pylint: disable=global-statement,invalid-name
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
		try:
			if RUNNING_ON_LINUX:
				configure_iptables()
			elif RUNNING_ON_MACOS:
				configure_macos_firewall()
		except Exception as err:  # pylint: disable=broad-except
			logger.error("Failed to configure firewall: %s", err, exc_info=True)

		logger.debug("Starting opsiclientd")
		opsiclientd = OpsiclientdPosix()
		opsiclientd.start()

		try:
			while opsiclientd.is_alive():
				time.sleep(1)

			logger.debug("Stopping opsiclientd")
			opsiclientd.join(60)
			logger.debug("Stopped")
		except Exception as err:  # pylint: disable=broad-except
			logger.error(err, exc_info=True)
		finally:
			if options.pidFile:
				logger.debug("Removing PID file")
				try:
					os.remove(options.pidFile)
					logger.debug("PID file removed")
				except OSError as oserr:
					logger.debug("Removing pid file failed: %s", oserr)
