# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
main for posix
"""

import os
import signal
import sys
import time
from signal import SIGHUP, SIGINT, SIGTERM
from types import FrameType

from opsicommon.logging import LOG_NONE, get_logger, log_context, logging_config
from opsicommon.logging import init_logging as oc_init_logging

from opsiclientd import DEFAULT_STDERR_LOG_FORMAT, init_logging, parser
from opsiclientd.Config import Config
from opsiclientd.nonfree.Posix import OpsiclientdPosix
from opsiclientd.Opsiclientd import Opsiclientd
from opsiclientd.setup import setup

opsiclientd: Opsiclientd | None = None
logger = get_logger("opsiclientd")


def signal_handler(signo: int, stackFrame: FrameType | None) -> None:
	logger.notice("Received signal %s, stopping opsiclientd", signo)
	if opsiclientd:
		opsiclientd.stop()


def daemonize(stdin: str = "/dev/null", stdout: str = "/dev/null", stderr: str = "/dev/null") -> None:
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
	with open(stdin, "rb", 0) as file:
		os.dup2(file.fileno(), sys.stdin.fileno())
	with open(stdout, "rb", 0) as file:
		os.dup2(file.fileno(), sys.stdout.fileno())
	with open(stderr, "rb", 0) as file:
		os.dup2(file.fileno(), sys.stderr.fileno())


def write_pid_file(path: str) -> None:
	if path:
		with open(path, "w", encoding="utf-8") as pidFile:
			pidFile.write(str(os.getpid()))


def main() -> None:
	global opsiclientd
	log_dir = Config().get("global", "log_dir")

	parser.add_argument(
		"--no-signal-handlers", "-t", dest="signalHandlers", action="store_false", default=True, help="Do not register signal handlers."
	)
	parser.add_argument("--daemon", "-D", dest="daemon", action="store_true", default=False, help="Daemonize process.")
	parser.add_argument("--pid-file", dest="pidFile", default=None, help="Write the PID into this file.")

	options = parser.parse_args()
	if options.config_file:
		Config().set("global", "config_file", options.config_file)

	if options.action == "setup":
		oc_init_logging(stderr_level=options.logLevel, stderr_format=DEFAULT_STDERR_LOG_FORMAT)
		setup(full=True, options=options)
		return

	if options.action == "download-from-depot":
		oc_init_logging(stderr_level=options.logLevel, stderr_format=DEFAULT_STDERR_LOG_FORMAT)
		from opsiclientd.OpsiService import download_from_depot

		Config().readConfigFile()
		download_from_depot(*options.arguments)
		return

	init_logging(log_dir=log_dir, stderr_level=options.logLevel, log_filter=options.logFilter)

	with log_context({"instance": "opsiclientd"}):
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

		logger.debug("Starting opsiclientd")
		opsiclientd = OpsiclientdPosix()
		opsiclientd.start()

		try:
			while opsiclientd.is_alive():
				time.sleep(1)

			logger.debug("Stopping opsiclientd")
			opsiclientd.join(60)
			logger.debug("Stopped")
		except Exception as err:
			logger.error(err, exc_info=True)
		finally:
			if options.pidFile:
				logger.debug("Removing PID file")
				try:
					os.remove(options.pidFile)
					logger.debug("PID file removed")
				except OSError as oserr:
					logger.debug("Removing pid file failed: %s", oserr)
