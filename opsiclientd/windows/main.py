# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
main for windows
"""

import os
import sys
import time
from datetime import datetime

import ntsecuritycon  # type: ignore[import]
import opsicommon.logging  # type: ignore[import]
import psutil  # type: ignore[import]
import win32api  # type: ignore[import]

# pyright: reportMissingImports=false
import win32con  # type: ignore[import]
import win32process  # type: ignore[import]
import win32security  # type: ignore[import]
from opsicommon.logging import LOG_NONE, get_logger
from opsicommon.logging import init_logging as oc_init_logging

from opsiclientd import DEFAULT_STDERR_LOG_FORMAT, init_logging, parser
from opsiclientd.Config import Config
from opsiclientd.setup import setup

# STARTUP_LOG = r"c:\opsi.org\log\opsiclientd_startup.log"
STARTUP_LOG: str | None = None

logger = get_logger()


def startup_log(message: str) -> None:
	if not STARTUP_LOG:
		return
	if os.path.isdir(os.path.dirname(STARTUP_LOG)):
		with open(STARTUP_LOG, "a", encoding="utf-8") as file:
			file.write(f"{datetime.now()} {message}\n")


def run_as_system(command: str) -> None:
	currentProcess = win32api.OpenProcess(win32con.MAXIMUM_ALLOWED, False, os.getpid())
	currentProcessToken = win32security.OpenProcessToken(currentProcess, win32con.MAXIMUM_ALLOWED)
	duplicatedCurrentProcessToken = win32security.DuplicateTokenEx(
		ExistingToken=currentProcessToken,
		DesiredAccess=win32con.MAXIMUM_ALLOWED,
		ImpersonationLevel=win32security.SecurityImpersonation,
		TokenType=ntsecuritycon.TokenImpersonation,
		TokenAttributes=None,
	)
	_id = win32security.LookupPrivilegeValue(None, win32security.SE_DEBUG_NAME)  # type: ignore[arg-type]
	newprivs = [(_id, win32security.SE_PRIVILEGE_ENABLED)]
	win32security.AdjustTokenPrivileges(duplicatedCurrentProcessToken, False, newprivs)  # type: ignore[arg-type]

	win32security.SetThreadToken(win32api.GetCurrentThread(), duplicatedCurrentProcessToken)  # type: ignore[no-untyped-call]

	currentProcessToken = win32security.OpenThreadToken(win32api.GetCurrentThread(), win32con.MAXIMUM_ALLOWED, False)  # type: ignore[no-untyped-call]
	sessionId = win32security.GetTokenInformation(currentProcessToken, ntsecuritycon.TokenSessionId)

	pid = None
	for proc in psutil.process_iter():
		try:
			if proc.name() == "lsass.exe":
				pid = proc.pid
				break
		except psutil.AccessDenied:
			pass
	if not pid:
		raise RuntimeError("Failed to get pid of lsass.exe")

	lsassProcess = win32api.OpenProcess(win32con.MAXIMUM_ALLOWED, False, pid)
	lsassProcessToken = win32security.OpenProcessToken(lsassProcess, win32con.MAXIMUM_ALLOWED)

	systemToken = win32security.DuplicateTokenEx(
		ExistingToken=lsassProcessToken,
		DesiredAccess=win32con.MAXIMUM_ALLOWED,
		ImpersonationLevel=win32security.SecurityImpersonation,
		TokenType=ntsecuritycon.TokenImpersonation,
		TokenAttributes=None,
	)

	privs = win32security.GetTokenInformation(systemToken, ntsecuritycon.TokenPrivileges)
	newprivs = []
	# enable all privileges
	for privtuple in privs:
		newprivs.append((privtuple[0], win32security.SE_PRIVILEGE_ENABLED))
	privs = tuple(newprivs)
	win32security.AdjustTokenPrivileges(systemToken, False, newprivs)  # type: ignore[arg-type]

	win32security.SetThreadToken(win32api.GetCurrentThread(), systemToken)  # type: ignore[no-untyped-call]

	hToken = win32security.DuplicateTokenEx(
		ExistingToken=lsassProcessToken,
		DesiredAccess=win32con.MAXIMUM_ALLOWED,
		ImpersonationLevel=win32security.SecurityImpersonation,
		TokenType=ntsecuritycon.TokenPrimary,
		TokenAttributes=None,
	)
	win32security.SetTokenInformation(hToken, ntsecuritycon.TokenSessionId, sessionId)

	privs = win32security.GetTokenInformation(hToken, ntsecuritycon.TokenPrivileges)
	newprivs = []
	# enable all privileges
	for privtuple in privs:
		newprivs.append((privtuple[0], win32security.SE_PRIVILEGE_ENABLED))
	privs = tuple(newprivs)
	win32security.AdjustTokenPrivileges(hToken, False, newprivs)  # type: ignore[arg-type]

	si = win32process.STARTUPINFO()
	dwCreationFlags = win32con.CREATE_NEW_CONSOLE
	win32process.CreateProcessAsUser(hToken, None, command, None, None, 1, dwCreationFlags, None, None, si)  # type: ignore[arg-type]


def get_integrity_level() -> str:
	currentProcess = win32api.OpenProcess(win32con.MAXIMUM_ALLOWED, False, os.getpid())
	currentProcessToken = win32security.OpenProcessToken(currentProcess, win32con.MAXIMUM_ALLOWED)
	sid, _unused = win32security.GetTokenInformation(currentProcessToken, ntsecuritycon.TokenIntegrityLevel)
	return win32security.ConvertSidToStringSid(sid)


def main() -> None:
	startup_log("windows.main")
	log_dir = Config().get("global", "log_dir")
	parent = psutil.Process(os.getpid()).parent()
	parent_name = parent.name() if parent else None
	# https://stackoverflow.com/questions/25770873/python-windows-service-pyinstaller-executables-error-1053

	startup_log(f"argv={sys.argv} parent_name={parent_name}")

	if len(sys.argv) == 1 and parent_name == "services.exe":
		startup_log("import start service")
		from opsiclientd.windows.service import start_service

		startup_log("init logging")
		init_logging(stderr_level=LOG_NONE, log_dir=log_dir)
		startup_log("start service")
		start_service()
		return

	if any(arg in sys.argv[1:] for arg in ("install", "update", "remove", "start", "stop", "restart")):
		from opsiclientd.windows.service import handle_commandline

		handle_commandline()
		return

	if any(arg in sys.argv[1:] for arg in ("setup", "download-from-depot", "--version", "--help")):
		options = parser.parse_args()
		if options.config_file:
			Config().set("global", "config_file", options.config_file)
		if options.action == "setup":
			oc_init_logging(stderr_level=options.logLevel, stderr_format=DEFAULT_STDERR_LOG_FORMAT)
			setup(full=True, options=options)
		elif options.action == "download-from-depot":
			oc_init_logging(stderr_level=options.logLevel, stderr_format=DEFAULT_STDERR_LOG_FORMAT)
			from opsiclientd.OpsiService import download_from_depot

			Config().readConfigFile()
			download_from_depot(*options.arguments)
		return

	if "--elevated" not in sys.argv and parent_name != "python.exe":
		executable = os.path.dirname(os.path.dirname(os.path.realpath(__file__))) + ".exe"
		args = " ".join(sys.argv[1:])
		command = executable + " " + args + " --elevated"
		try:
			run_as_system(command)
		except Exception as err:
			print(f"Failed to run {command} as system: {err}", file=sys.stderr)
			raise
		return

	integrity_level = get_integrity_level()
	if int(integrity_level.split("-")[-1]) < 12288:
		raise RuntimeError(f"opsiclientd.exe must be run as service or from an elevated cmd.exe (integrity_level={integrity_level})")

	if "--elevated" in sys.argv:
		sys.argv.remove("--elevated")
	options = parser.parse_args()
	if options.config_file:
		Config().set("global", "config_file", options.config_file)

	init_logging(log_dir=log_dir, stderr_level=options.logLevel, log_filter=options.logFilter)

	with opsicommon.logging.log_context({"instance": "opsiclientd"}):
		logger.notice("Running as user: %s", win32api.GetUserName())
		if parent:
			logger.notice("Parent process: %s (%s)", parent.name(), parent.pid)
		logger.debug(os.environ)
		from .opsiclientd import opsiclientd_factory

		opsiclientd = opsiclientd_factory()
		try:
			opsiclientd.start()
			while True:
				time.sleep(1)
		except KeyboardInterrupt:
			logger.essential("KeyboardInterrupt #1 -> stop")
			opsiclientd.stop()
			try:
				opsiclientd.join(15)
			except KeyboardInterrupt:
				logger.essential("KeyboardInterrupt #2 -> kill process")
				psutil.Process(os.getpid()).kill()
