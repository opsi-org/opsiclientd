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
import sys
import time
import psutil
import win32con
import win32api
import win32process
import win32security
import ntsecuritycon
import servicemanager
import win32serviceutil

import opsicommon.logging
from opsicommon.logging import logger, LOG_NONE
from OPSI import System

from opsiclientd import init_logging, parser

def run_as_system(command):
	currentProcess = win32api.OpenProcess(win32con.MAXIMUM_ALLOWED, False, os.getpid())
	currentProcessToken = win32security.OpenProcessToken(currentProcess, win32con.MAXIMUM_ALLOWED)
	duplicatedCurrentProcessToken = win32security.DuplicateTokenEx(
		ExistingToken=currentProcessToken,
		DesiredAccess=win32con.MAXIMUM_ALLOWED,
		ImpersonationLevel=win32security.SecurityImpersonation,
		TokenType=ntsecuritycon.TokenImpersonation,
		TokenAttributes=None
	)
	id = win32security.LookupPrivilegeValue(None, win32security.SE_DEBUG_NAME)
	newprivs = [(id, win32security.SE_PRIVILEGE_ENABLED)]
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

	s = win32process.STARTUPINFO()
	dwCreationFlags = win32con.CREATE_NEW_CONSOLE
	win32process.CreateProcessAsUser(hToken, None, command, None, None, 1, dwCreationFlags, None, None, s)

def get_integrity_level():
	currentProcess = win32api.OpenProcess(win32con.MAXIMUM_ALLOWED, False, os.getpid())
	currentProcessToken = win32security.OpenProcessToken(currentProcess, win32con.MAXIMUM_ALLOWED)
	sid, i = win32security.GetTokenInformation(currentProcessToken, ntsecuritycon.TokenIntegrityLevel)
	# S-1-16-0      Untrusted Mandatory Level
	# S-1-16-4096   Low Mandatory Level
	# S-1-16-8192   High Mandatory Level
	# S-1-16-12288  System Mandatory Level
	return win32security.ConvertSidToStringSid(sid)

def main():
	log_dir = os.path.join(System.getSystemDrive() + "\\opsi.org\\log")
	parent = psutil.Process(os.getpid()).parent()
	parent_name = parent.name() if parent else None
	# https://stackoverflow.com/questions/25770873/python-windows-service-pyinstaller-executables-error-1053
	#if os.environ.get("USERNAME", "$").endswith("$") and len(sys.argv) == 1:
	if parent_name == "services.exe":
		from opsiclientd.windows.service import start_service
		init_logging(stderr_level=LOG_NONE, log_dir=log_dir)
		start_service()
	else:
		if any(arg in sys.argv[1:] for arg in ("install", "update", "remove", "start", "stop", "restart")):
			from opsiclientd.windows.service import handle_commandline
			handle_commandline()
		else:
			integrity_level = get_integrity_level()
			if not "--elevated" in sys.argv and not "--help" in sys.argv and not "--version" in sys.argv and parent_name != "python.exe":
				executable = os.path.dirname(os.path.dirname(os.path.realpath(__file__))) + ".exe"
				args = " ".join(sys.argv[1:])
				#subprocess.run("whoami /user /priv")
				#print(integrity_level)
				if integrity_level != "S-1-16-12288" or parent_name != "cmd.exe":
					from opsiclientd.windows.service import handle_commandline
					handle_commandline()
					#print("opsiclientd.exe must be run as service or from an elevated cmd.exe", file=sys.stderr)
					return
					"""
					#if not ctypes.windll.shell32.IsUserAnAdmin() or (parent and parent.name().lower() == "explorer.exe"):
					# workaround permission problems
					# opsiclientd must be started from an elevated cmd.exe
					from win32com.shell.shell import ShellExecuteEx
					from win32com.shell import shellcon
					#showCmd = win32con.SW_HIDE
					showCmd = win32con.SW_SHOW
					lpVerb = 'runas'  # causes UAC elevation prompt.
					procInfo = ShellExecuteEx(
						nShow=showCmd,
						fMask=shellcon.SEE_MASK_NOCLOSEPROCESS,
						lpVerb=lpVerb,
						#lpFile=executable,
						#lpParameters=args
						lpFile="cmd.exe",
						lpParameters="" #"/c " + executable + " " + args
					)
					#subprocess.run(["powershell.exe", "start", "cmd.exe", "-ArgumentList", "", "-Verb", "Runas"])
					#subprocess.run(["powershell.exe", "start", "cmd.exe", "-Verb", "Runas"])
					#subprocess.run(["powershell.exe", "start", executable, "-Verb", "Runas"])
					#
					#ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
					return
					"""
				else:
					#opsicommon.logging.logging_config(log_file="c:\\tmp\\opsiclientd-startup.txt", file_level=LOG_DEBUG)
					#logger.notice("Running as user: %s", win32api.GetUserName())
					#if parent:
					#	logger.notice("Parent process: %s (%s)", parent.name(), parent.pid)
					command = executable + " " + args + " --elevated"
					try:
						run_as_system(command)
					except Exception as e:
						print(f"Failed to run {command} as system: {e}", file=sys.stderr)
						raise
				return
			
			if "--elevated" in sys.argv:
				sys.argv.remove("--elevated")
			options = parser.parse_args()
			init_logging(log_dir=log_dir, stderr_level=options.logLevel, log_filter=options.logFilter)
			with opsicommon.logging.log_context({'instance', 'opsiclientd'}):
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
