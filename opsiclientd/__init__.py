# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
opsiclientd Library.
"""

from __future__ import annotations

import argparse
import http
import os
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from typing import Union

import psutil
from OPSI import __version__ as python_opsi_version  # type: ignore[import]
from OPSI.System import execute, which  # type: ignore[import]
from opsicommon import __version__ as opsicommon_version
from opsicommon.logging import (
	LOG_DEBUG,
	LOG_NONE,
	LOG_TRACE,
	get_all_handlers,
	get_logger,
	log_context,
	logging_config,
	set_filter_from_string,
)

from opsiclientd.Config import Config
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS

__version__ = "4.3.2.1"

DEFAULT_STDERR_LOG_FORMAT = (
	"%(log_color)s[%(opsilevel)d] [%(asctime)s.%(msecs)03d]%(reset)s [%(contextstring)-40s] %(message)s   (%(filename)s:%(lineno)d)"
)
DEFAULT_FILE_LOG_FORMAT = DEFAULT_STDERR_LOG_FORMAT.replace("%(log_color)s", "").replace("%(reset)s", "")

config = Config()
logger = get_logger()

parser = argparse.ArgumentParser()
parser.add_argument(
	"--version",
	"-V",
	action="version",
	version=f"{__version__} [python-opsi={python_opsi_version},python-opsi-common={opsicommon_version}]",
)
parser.add_argument(
	"--log-level", "-l", dest="logLevel", type=int, choices=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], default=LOG_NONE, help="Set the log-level."
)
parser.add_argument(
	"--log-filter", dest="logFilter", default=None, help="Filter log records contexts (<ctx-name-1>=<val1>[,val2][;ctx-name-2=val3])."
)
parser.add_argument(
	"--config-file",
	default=None,  # config.get("global", "config_file"),
	help="Path to config file",
)
parser.add_argument("--service-address", default=None, help="Service address to use for setup.")
parser.add_argument("--service-username", default=None, help="Username to use for service connection (setup).")
parser.add_argument("--service-password", default=None, help="Password to use for service connection (setup).")
parser.add_argument("--client-id", default=None, help="Client id to use for setup (fqdn is used if omitted).")
parser.add_argument(
	"action",
	nargs="?",
	choices=("start", "stop", "restart", "install", "update", "remove", "setup", "download-from-depot"),
	default=None,
	metavar="ACTION",
	help="The ACTION to perform (start / stop / restart / install / update / remove / setup / download-from-depot).",
)
parser.add_argument("arguments", nargs="*", default=None)


def get_opsiclientd_pid() -> int | None:
	our_pid = os.getpid()
	for proc in psutil.process_iter():
		if proc.pid == our_pid:
			continue

		if proc.name() in ("opsiclientd", "opsiclientd.exe") or (
			proc.name() in ("python", "python3") and ("opsiclientd" in proc.cmdline() or "opsiclientd.__main__" in " ".join(proc.cmdline()))
		):
			return proc.pid
	return None


def init_logging(log_dir: str, stderr_level: int = LOG_NONE, log_filter: str | None = None) -> None:
	if not os.path.isdir(log_dir):
		log_dir = tempfile.gettempdir()
	log_file = os.path.join(log_dir, "opsiclientd.log")

	config.set("global", "log_file", log_file)

	log_file_without_ext, ext = os.path.splitext(log_file)  # ext contains '.'

	for i in (9, 8, 7, 6, 5, 4, 3, 2, 1, 0):
		old_lf = f"{log_file_without_ext}{ext}.{i-1}"  # old format
		new_lf = f"{log_file_without_ext}_{i}{ext}"
		if i > 0 and os.path.exists(old_lf):
			try:
				# Rename existing log file from old to new format
				os.rename(old_lf, new_lf)
			except Exception as err:
				logger.error("Failed to rename %s to %s: %s", old_lf, new_lf, err)

	logging_config(
		stderr_level=stderr_level,
		stderr_format=DEFAULT_STDERR_LOG_FORMAT,
		log_file=log_file,
		file_level=LOG_DEBUG,
		file_format=DEFAULT_FILE_LOG_FORMAT,
		file_rotate_max_bytes=int(float(config.get("global", "max_log_size")) * 1_000_000),
		file_rotate_backup_count=config.get("global", "keep_rotated_logs"),
	)

	def namer(default_name: str) -> str:
		tmp = default_name.rsplit(".", 2)
		return f"{tmp[0]}_{int(tmp[2]) - 1}.{tmp[1]}"

	handler = get_all_handlers(handler_type=RotatingFileHandler)[0]
	handler.namer = namer  # type: ignore[attr-defined]
	try:
		handler.doRollover()  # type: ignore[attr-defined]
	except Exception as err:
		logger.error("Failed to rotate log file: %s", err)
	if log_filter:
		set_filter_from_string(log_filter)

	logger.essential("Log file %s started", log_file)

	def log_http(*args: str) -> None:
		if logger.level < LOG_TRACE or len(args) < 2:
			return
		with log_context({"module": "http client"}):
			if args[0] == "header:":
				logger.trace("<<< %s %s", args[1], args[2])
			elif args[0] == "reply:":
				logger.trace("<<< %s", args[1][1:-4])
			elif args[0] == "send:":
				header_end = args[1].find(r"\r\n\r\n")
				if header_end != -1:
					for header in args[1][:header_end].split(r"\r\n"):
						logger.trace(">>> %s", header.lstrip("b'"))
			else:
				logger.trace(args)

	http.client.HTTPConnection.debuglevel = 1
	http.client.print = log_http  # type: ignore[attr-defined]


def check_signature(bin_dir: str) -> None:
	logger.info("check_signature is called")
	if not sys.platform == "win32":
		return  # Not yet implemented

	windowsVersion = sys.getwindowsversion()
	if windowsVersion.major < 6 or (windowsVersion.major == 6 and windowsVersion.minor < 4):
		return  # Get-AuthenticodeSignature is only defined for versions since 2016

	binary_list = [
		os.path.join(bin_dir, "opsiclientd.exe"),
		os.path.join(bin_dir, "opsiclientd_rpc.exe"),
		os.path.join(bin_dir, "action_processor_starter.exe"),
	]
	for binary in binary_list:
		cmd = f"powershell.exe -ExecutionPolicy Bypass -Command \"(Get-AuthenticodeSignature '{binary}').Status -eq 'Valid'\""

		result = execute(cmd, captureStderr=True, waitForEnding=True, timeout=30)
		logger.debug(result)
		if "True" not in result:
			raise ValueError(f"Invalid Signature of file {binary}")
	logger.notice("Successfully verified %s", binary_list)


def notify_posix_terminals(message: str) -> None:
	if not RUNNING_ON_WINDOWS and which("wall"):
		# On non-Windows systems, use 'wall' to display a message before reboot/shutdown
		command = [which("wall"), "-n", message]
		logger.debug("Executing %s", command)
		try:
			execute(command, shell=False)
		except Exception as err:
			logger.warning("Failed to notify users via 'wall': %s", err)
