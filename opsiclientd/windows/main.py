# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0
"""
main for windows
"""

import os
import sys
import time
import psutil
# pyright: reportMissingImports=false
import win32con # pylint: disable=import-error
import win32api # pylint: disable=import-error
import win32process # pylint: disable=import-error
import win32security # pylint: disable=import-error
import ntsecuritycon # pylint: disable=import-error

import opsicommon.logging
from opsicommon.logging import (
	logger, LOG_NONE, init_logging as oc_init_logging
)
from OPSI import System

from opsiclientd import init_logging, parser, DEFAULT_STDERR_LOG_FORMAT
from opsiclientd.setup import setup


def run_as_system(command): # pylint: disable=too-many-locals
	currentProcess = win32api.OpenProcess(win32con.MAXIMUM_ALLOWED, False, os.getpid())
	currentProcessToken = win32security.OpenProcessToken(currentProcess, win32con.MAXIMUM_ALLOWED)
	duplicatedCurrentProcessToken = win32security.DuplicateTokenEx(
		ExistingToken=currentProcessToken,
		DesiredAccess=win32con.MAXIMUM_ALLOWED,
		ImpersonationLevel=win32security.SecurityImpersonation,
		TokenType=ntsecuritycon.TokenImpersonation,
		TokenAttributes=None
	)
	_id = win32security.LookupPrivilegeValue(None, win32security.SE_DEBUG_NAME)
	newprivs = [(_id, win32security.SE_PRIVILEGE_ENABLED)]
	win32security.AdjustTokenPrivileges(duplicatedCurrentProcessToken, False, newprivs)

	win32security.SetThreadToken(win32api.GetCurrentThread(), duplicatedCurrentProcessToken)

	currentProcessToken = win32security.OpenThreadToken(win32api.GetCurrentThread(), win32con.MAXIMUM_ALLOWED, False)
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
	lsassProcessToken = win32security.OpenProcessToken(
		lsassProcess,
		win32con.MAXIMUM_ALLOWED
	)

	systemToken = win32security.DuplicateTokenEx(
		ExistingToken=lsassProcessToken,
		DesiredAccess=win32con.MAXIMUM_ALLOWED,
		ImpersonationLevel=win32security.SecurityImpersonation,
		TokenType=ntsecuritycon.TokenImpersonation,
		TokenAttributes=None
	)

	privs = win32security.GetTokenInformation(systemToken, ntsecuritycon.TokenPrivileges)
	newprivs = []
	# enable all privileges
	for privtuple in privs:
		newprivs.append((privtuple[0], win32security.SE_PRIVILEGE_ENABLED))
	privs = tuple(newprivs)
	win32security.AdjustTokenPrivileges(systemToken, False, newprivs)

	win32security.SetThreadToken(win32api.GetCurrentThread(), systemToken)

	hToken = win32security.DuplicateTokenEx(
		ExistingToken=lsassProcessToken,
		DesiredAccess=win32con.MAXIMUM_ALLOWED,
		ImpersonationLevel=win32security.SecurityImpersonation,
		TokenType=ntsecuritycon.TokenPrimary,
		TokenAttributes=None
	)
	win32security.SetTokenInformation(hToken, ntsecuritycon.TokenSessionId, sessionId)

	privs = win32security.GetTokenInformation(hToken, ntsecuritycon.TokenPrivileges)
	newprivs = []
	# enable all privileges
	for privtuple in privs:
		newprivs.append((privtuple[0], win32security.SE_PRIVILEGE_ENABLED))
	privs = tuple(newprivs)
	win32security.AdjustTokenPrivileges(hToken, False, newprivs)

	si = win32process.STARTUPINFO()
	dwCreationFlags = win32con.CREATE_NEW_CONSOLE
	win32process.CreateProcessAsUser(hToken, None, command, None, None, 1, dwCreationFlags, None, None, si)

def get_integrity_level():
	currentProcess = win32api.OpenProcess(win32con.MAXIMUM_ALLOWED, False, os.getpid())
	currentProcessToken = win32security.OpenProcessToken(currentProcess, win32con.MAXIMUM_ALLOWED)
	sid, _unused = win32security.GetTokenInformation(currentProcessToken, ntsecuritycon.TokenIntegrityLevel)
	return win32security.ConvertSidToStringSid(sid)

def main(): # pylint: disable=too-many-statements
	log_dir = os.path.join(System.getSystemDrive() + "\\opsi.org\\log")
	parent = psutil.Process(os.getpid()).parent()
	parent_name = parent.name() if parent else None
	# https://stackoverflow.com/questions/25770873/python-windows-service-pyinstaller-executables-error-1053

	if len(sys.argv) == 1 and parent_name == "services.exe":
		from opsiclientd.windows.service import start_service # pylint: disable=import-outside-toplevel
		init_logging(stderr_level=LOG_NONE, log_dir=log_dir)
		start_service()
		return

	if any(arg in sys.argv[1:] for arg in ("install", "update", "remove", "start", "stop", "restart")):
		from opsiclientd.windows.service import handle_commandline # pylint: disable=import-outside-toplevel
		handle_commandline()
		return

	if any(arg in sys.argv[1:] for arg in ("setup", "--version", "--help")):
		options = parser.parse_args()
		if options.action == "setup":
			oc_init_logging(stderr_level=options.logLevel, stderr_format=DEFAULT_STDERR_LOG_FORMAT)
			setup(full=True, options=options)
		return

	if "--elevated" not in sys.argv and parent_name != "python.exe":
		executable = os.path.dirname(os.path.dirname(os.path.realpath(__file__))) + ".exe"
		args = " ".join(sys.argv[1:])
		command = executable + " " + args + " --elevated"
		try:
			run_as_system(command)
		except Exception as err: # pylint: disable=broad-except
			print(f"Failed to run {command} as system: {err}", file=sys.stderr)
			raise
		return

	integrity_level = get_integrity_level()
	if int(integrity_level.split("-")[-1]) < 12288:
		print(f"opsiclientd.exe must be run as service or from an elevated cmd.exe (integrity_level={integrity_level})", file=sys.stderr)
		time.sleep(3)
		sys.exit(1)

	if "--elevated" in sys.argv:
		sys.argv.remove("--elevated")
	options = parser.parse_args()

	init_logging(log_dir=log_dir, stderr_level=options.logLevel, log_filter=options.logFilter)

	with opsicommon.logging.log_context({'instance', 'opsiclientd'}):
		logger.notice("Running as user: %s", win32api.GetUserName())
		if parent:
			logger.notice("Parent process: %s (%s)", parent.name(), parent.pid)
		logger.debug(os.environ)
		from .opsiclientd import opsiclientd_factory # pylint: disable=import-outside-toplevel
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
