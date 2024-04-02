# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
opsiclientd.windows.opsiclientd
"""

import glob
import os
import random
import string
import subprocess
import sys
import threading
import time
import winreg  # type: ignore[import] # pylint: disable=import-error
from enum import StrEnum

# pyright: reportMissingImports=false
from typing import Any

import pywintypes  # type: ignore[import]
import win32api  # type: ignore[import]
import win32com.client  # type: ignore[import]
import win32com.server.policy  # type: ignore[import]
import win32con  # type: ignore[import]
import win32net  # type: ignore[import]
import win32netcon  # type: ignore[import]
import win32security  # type: ignore[import]
from OPSI import System  # type: ignore[import]
from opsicommon.logging import get_logger  # type: ignore[import]
from opsicommon.types import forceBool  # type: ignore[import]

from opsiclientd import config
from opsiclientd.Config import OPSI_SETUP_USER_NAME
from opsiclientd.Opsiclientd import Opsiclientd
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS

if not RUNNING_ON_WINDOWS:
	WindowsError = RuntimeError

logger = get_logger("opsiclientd")


def opsiclientd_factory():
	windowsVersion = sys.getwindowsversion()  # type: ignore[attr-defined]
	if windowsVersion.major == 5:  # NT5: XP
		return OpsiclientdNT5()
	if windowsVersion.major >= 6:  # NT6: Vista / Windows7 and later
		return OpsiclientdNT6()
	raise RuntimeError(f"Windows version {windowsVersion} not supported")


class OpsiclientdNT(Opsiclientd):
	def __init__(self):
		Opsiclientd.__init__(self)
		self._ms_update_installer = None

	def suspendBitlocker(self):
		logger.notice("Suspending bitlocker for one reboot if active")
		try:
			System.execute(
				'powershell.exe -ExecutionPolicy Bypass -Command "'
				"foreach($v in Get-BitLockerVolume)"
				"{if ($v.EncryptionPercentage -gt 0)"
				'{$v | Suspend-BitLocker -RebootCount 1}}"',
				captureStderr=True,
				waitForEnding=True,
				timeout=20,
			)

		except Exception as err:
			logger.error("Failed to suspend bitlocker: %s", err, exc_info=True)

	def rebootMachine(self, waitSeconds=3):
		if config.get("global", "suspend_bitlocker_on_reboot"):
			windowsVersion = sys.getwindowsversion()
			if (windowsVersion.major == 6 and windowsVersion.minor >= 4) or windowsVersion.major > 6:  # Win10 and later
				self.suspendBitlocker()
		super().rebootMachine(waitSeconds)

	def clearRebootRequest(self):
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested", 0)

	def clearShutdownRequest(self):
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested", 0)

	def isRebootRequested(self):
		try:
			rebootRequested = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested")
		except Exception as error:
			logger.warning("Failed to get RebootRequested from registry: %s", error)
			rebootRequested = 0

		logger.notice("Reboot request in Registry: %s", rebootRequested)
		if rebootRequested == 2:
			# Logout
			logger.info("Logout requested")
			self.clearRebootRequest()
			return False

		return forceBool(rebootRequested)

	def isShutdownRequested(self):
		try:
			shutdownRequested = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested")
		except Exception as err:
			logger.info("Failed to get shutdownRequested from registry: %s", err)
			shutdownRequested = 0

		logger.notice("Shutdown request in Registry: %s", shutdownRequested)
		return forceBool(shutdownRequested)

	def isWindowsRebootPending(self):
		import winreg

		import win32process  # type: ignore[import]

		class CheckType(StrEnum):
			KEY_EXISTS = "key_exists"
			ANY_SUB_KEY_EXISTS = "any_sub_key_exists"
			VALUE_EXISTS = "value_exists"
			VALUE_NOT_ZERO = "value_not_zero"

		checks = (
			(
				r"\SOFTWARE\Microsoft\Updates",
				"UpdateExeVolatile",
				CheckType.VALUE_NOT_ZERO,
			),
			(
				r"\SYSTEM\CurrentControlSet\Control\Session Manager",
				"PendingFileRenameOperations",
				CheckType.VALUE_EXISTS,
			),
			(
				r"\SYSTEM\CurrentControlSet\Control\Session Manager",
				"PendingFileRenameOperations2",
				CheckType.VALUE_EXISTS,
			),
			(
				r"\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
				None,
				CheckType.KEY_EXISTS,
			),
			(
				r"\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Services\Pending",
				None,
				CheckType.ANY_SUB_KEY_EXISTS,
			),
			(
				r"\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\PostRebootReporting",
				None,
				CheckType.KEY_EXISTS,
			),
			(
				r"\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce",
				"DVDRebootSignal",
				CheckType.VALUE_EXISTS,
			),
			(
				r"\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
				None,
				CheckType.KEY_EXISTS,
			),
			(
				r"\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootInProgress",
				None,
				CheckType.KEY_EXISTS,
			),
			(
				r"\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\PackagesPending",
				None,
				CheckType.KEY_EXISTS,
			),
			(
				r"\SOFTWARE\Microsoft\ServerManager\CurrentRebootAttempts",
				None,
				CheckType.KEY_EXISTS,
			),
			(
				r"\SYSTEM\CurrentControlSet\Services\Netlogon",
				"JoinDomain",
				CheckType.VALUE_EXISTS,
			),
			(
				r"\SYSTEM\CurrentControlSet\Services\Netlogon",
				"AvoidSpnSet",
				CheckType.VALUE_EXISTS,
			),
		)

		is_windows_reboot_pending = False

		access = winreg.KEY_READ
		if win32process.IsWow64Process():
			access |= winreg.KEY_WOW64_64KEY

		for key, sub_key, value_name, check in checks:
			reboot_check_result = False
			key_exists = False
			value_exists = False
			any_sub_key_exists = False
			reg_value = None
			try:
				with winreg.OpenKey(key=winreg.HKEY_LOCAL_MACHINE, sub_key=sub_key, access=access) as key:
					key_exists = True
					if check == CheckType.ANY_SUB_KEY_EXISTS:
						number_of_sub_keys = winreg.QueryInfoKey(key)[0]
						any_sub_key_exists = number_of_sub_keys > 0
					if value_name:
						reg_value, _value_type = winreg.QueryValueEx(key, value_name)
						value_exists = True
			except Exception:
				pass

			if CheckType.KEY_EXISTS:
				reboot_check_result = key_exists
			elif CheckType.VALUE_EXISTS:
				reboot_check_result = value_exists
			elif CheckType.VALUE_NOT_ZERO:
				reboot_check_result = reg_value != 0
			elif CheckType.ANY_SUB_KEY_EXISTS:
				reboot_check_result = any_sub_key_exists

			if reboot_check_result:
				is_windows_reboot_pending = True

			logger.info(
				"Reboot check %r - %r - %r - %r: key_exists=%r, value_exists=%r, value=%r, result=%r",
				key,
				sub_key,
				value_name,
				check,
				key_exists,
				value_exists,
				reg_value,
				reboot_check_result,
			)
		return is_windows_reboot_pending

	def isWindowsInstallerBusy(self):
		if not self._ms_update_installer:
			from opsiclientd.windows import importWmiAndPythoncom

			(_wmi, _pythoncom) = importWmiAndPythoncom(importWmi=False, importPythoncom=True)
			_pythoncom.CoInitialize()
			session = win32com.client.Dispatch("Microsoft.Update.Session")
			self._ms_update_installer = session.CreateUpdateInstaller()
		installer_is_busy = self._ms_update_installer.isBusy
		if not installer_is_busy:
			logger.info(
				"IUpdateInstaller::get_RebootRequiredBeforeInstallation: %r", self._ms_update_installer.get_RebootRequiredBeforeInstallation
			)
		return installer_is_busy

	def loginUser(self, username, password):
		for session_id in System.getActiveSessionIds(protocol="console"):
			System.lockSession(session_id)
		for _unused in range(20):
			if self._controlPipe.credentialProviderConnected(login_capable=True):
				break
			time.sleep(0.5)
		if not self._controlPipe.credentialProviderConnected(login_capable=True):
			raise RuntimeError("No login capable opsi credential provider connected")
		logger.info("Login capable opsi credential provider connected, calling loginUser")
		for response in self._controlPipe.executeRpc("loginUser", username, password):
			logger.debug("loginUser response: %r", response)
			if not response.get("error") and response.get("result"):
				return True
			raise RuntimeError(f"opsi credential provider failed to login user '{username}': {response.get('error')}")

	def cleanup_opsi_setup_user(self, keep_sid: str | None = None):
		keep_profile = None
		modified = True
		while modified:
			modified = False
			# We need to start over iterating after key change
			with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList") as key:  # type: ignore[attr-defined]
				for idx in range(1024):
					try:
						profile_key = winreg.EnumKey(key, idx)  # type: ignore[attr-defined]
						logger.debug("Processing profile key %r", profile_key)
					except WindowsError as err:
						if err.errno == 22:  # type: ignore[attr-defined]
							logger.debug("No more subkeys")
							break
						logger.debug(err)

					sid = profile_key.replace(".bak", "")

					try:
						with winreg.OpenKey(key, profile_key) as subkey:  # type: ignore[attr-defined]
							profile_path = winreg.QueryValueEx(subkey, "ProfileImagePath")[0]  # type: ignore[attr-defined]
							if keep_sid and sid == keep_sid:
								keep_profile = profile_path
								continue
					except FileNotFoundError as err:
						logger.debug("Failed to read ProfileImagePath for SID %r: %s", sid, err)
						continue

					username = profile_path.split("\\")[-1].split(".")[0]
					if not username.startswith(OPSI_SETUP_USER_NAME):
						continue

					try:
						win32security.ConvertStringSidToSid(sid)
					except pywintypes.error:
						logger.debug("Not a valid SID %r", sid)
						continue

					try:
						win32api.RegUnLoadKey(win32con.HKEY_USERS, profile_key)  # type: ignore[arg-type]
					except pywintypes.error as err:
						logger.debug(err)

					exists = False
					try:
						win32security.LookupAccountSid(None, win32security.ConvertStringSidToSid(sid))  # type: ignore[arg-type]
						exists = True
					except pywintypes.error as err:
						logger.debug(err)

					if exists:
						logger.info("Deleting user %r, sid %r", username, sid)
						cmd = [
							"powershell.exe",
							"-ExecutionPolicy",
							"Bypass",
							"-Command",
							f"Remove-LocalUser -SID (New-Object 'Security.Principal.SecurityIdentifier' \"{sid}\") -Verbose",
						]
						logger.info("Executing: %s", cmd)
						res = subprocess.run(cmd, shell=False, capture_output=True, check=False, timeout=60)
						out = res.stdout.decode(errors="replace") + res.stderr.decode(errors="replace")
						if res.returncode == 0:
							logger.info("Command %s successful: %s", cmd, out)
							modified = True
						else:
							logger.warning("Failed to delete user %r %r (exitcode %d): %s", cmd, username, res.returncode, out)
							try:
								logger.info("Deleting user %r via windows api", username)
								win32net.NetUserDel(None, username)  # type: ignore[arg-type]
							except Exception as err:
								logger.warning("Failed to delete user %r via windows api: %s", username, err)

					else:
						logger.info("User %r, sid %r does not exist, deleting key", username, sid)
						try:
							winreg.DeleteKey(key, profile_key)  # type: ignore[attr-defined]
							modified = True
						except OSError as err:
							logger.debug(err)

					try:
						winreg.DeleteKey(winreg.HKEY_USERS, sid)  # type: ignore[attr-defined]
					except OSError as err:
						logger.debug(err)
					if modified:
						# Restart iteration
						break

		# takeown parameter /d is localized 😠
		res = subprocess.run("choice <nul 2>nul", capture_output=True, check=False, shell=True)
		yes = res.stdout.decode().split(",")[0].lstrip("[").strip()
		for pdir in glob.glob(f"c:\\users\\{OPSI_SETUP_USER_NAME}*"):
			if keep_profile and keep_profile.lower() == pdir.lower():
				continue
			logger.info("Deleting user dir '%s'", pdir)
			for cmd, shell, exit_codes_success in (
				(["takeown", "/a", "/d", yes, "/r", "/f", pdir], False, [0, 1]),
				(["del", pdir, "/f", "/s", "/q"], True, [0]),
				(["rd", pdir, "/s", "/q"], True, [0]),
			):
				logger.info("Executing: %s", cmd)
				res = subprocess.run(cmd, shell=shell, capture_output=True, check=False)
				out = res.stdout.decode(errors="replace") + res.stderr.decode(errors="replace")
				if res.returncode not in exit_codes_success:
					logger.warning("Command %s failed with exit code %s: %s", cmd, res.returncode, out)
				else:
					logger.info("Command %s successful: %s", cmd, out)

	def createOpsiSetupUser(self, admin=True, delete_existing=False) -> dict[str, Any]:
		# https://bugs.python.org/file46988/issue.py
		if sys.platform != "win32":
			return {}

		password_chars = [random.choice(string.ascii_letters + string.digits) for i in range(9)] + ["/", "?", "9", "a", "Z"]
		random.shuffle(password_chars)

		user_info = {
			"name": OPSI_SETUP_USER_NAME,
			"full_name": "opsi setup user",
			"comment": "auto created by opsi",
			"password": "".join(password_chars),
			"priv": win32netcon.USER_PRIV_USER,
			"flags": win32netcon.UF_NORMAL_ACCOUNT | win32netcon.UF_SCRIPT | win32netcon.UF_DONT_EXPIRE_PASSWD,
		}

		# Test if user exists
		user_sid = None
		try:
			win32net.NetUserGetInfo(None, str(user_info["name"]), 1)  # type: ignore[arg-type]
			user_sid = win32security.ConvertSidToStringSid(win32security.LookupAccountName(None, str(user_info["name"]))[0])
			logger.info("User '%s' exists, sid is '%s'", str(user_info["name"]), user_sid)
		except Exception as err:
			logger.info(err)

		self.cleanup_opsi_setup_user(keep_sid=None if delete_existing else user_sid)
		if delete_existing:
			user_sid = None

		# Hide user from login
		try:
			winreg.CreateKeyEx(
				winreg.HKEY_LOCAL_MACHINE,
				r"Software\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts",
				0,
				winreg.KEY_WOW64_64KEY | winreg.KEY_ALL_ACCESS,  # sysnative
			)
		except WindowsError:
			pass
		try:
			winreg.CreateKeyEx(
				winreg.HKEY_LOCAL_MACHINE,
				r"Software\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList",
				0,
				winreg.KEY_WOW64_64KEY | winreg.KEY_ALL_ACCESS,  # sysnative
			)
		except WindowsError:
			pass

		with winreg.OpenKey(
			winreg.HKEY_LOCAL_MACHINE,
			r"Software\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList",
			0,
			winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,  # sysnative
		) as reg_key:
			winreg.SetValueEx(reg_key, str(user_info["name"]), 0, winreg.REG_DWORD, 0)

		if user_sid:
			logger.info("Updating password of user '%s'", str(user_info["name"]))
			user_info_update = win32net.NetUserGetInfo(None, str(user_info["name"]), 1)  # type: ignore[arg-type]
			user_info_update["password"] = user_info["password"]
			win32net.NetUserSetInfo(None, str(user_info["name"]), 1, user_info_update)  # type: ignore[arg-type]
		else:
			logger.info("Creating user '%s'", str(user_info["name"]))
			win32net.NetUserAdd(None, 1, user_info)  # type: ignore[arg-type]

		user_sid = win32security.ConvertSidToStringSid(win32security.LookupAccountName(None, str(user_info["name"]))[0])
		subprocess.run(["icacls", os.path.dirname(sys.argv[0]), "/grant:r", f"*{user_sid}:(OI)(CI)RX"], check=False)
		subprocess.run(["icacls", os.path.dirname(config.get("global", "log_file")), "/grant:r", f"*{user_sid}:(OI)(CI)F"], check=False)
		subprocess.run(["icacls", os.path.dirname(config.get("global", "tmp_dir")), "/grant:r", f"*{user_sid}:(OI)(CI)F"], check=False)

		local_admin_group_sid = win32security.ConvertStringSidToSid("S-1-5-32-544")
		local_admin_group_name = win32security.LookupAccountSid(None, local_admin_group_sid)[0]  # type: ignore[arg-type]
		try:
			if admin:
				logger.info("Adding user '%s' to admin group", str(user_info["name"]))
				win32net.NetLocalGroupAddMembers(None, local_admin_group_name, 3, [{"domainandname": str(user_info["name"])}])  # type: ignore[arg-type]
			else:
				logger.info("Removing user '%s' from admin group", str(user_info["name"]))
				win32net.NetLocalGroupDelMembers(None, local_admin_group_name, [str(user_info["name"])])  # type: ignore[arg-type]
		except pywintypes.error as err:
			# 1377 - ERROR_MEMBER_NOT_IN_ALIAS
			#  The specified account name is not a member of the group.
			# 1378 # ERROR_MEMBER_IN_ALIAS
			#  The specified account name is already a member of the group.
			if err.winerror not in (1377, 1378):
				raise

		user_info_4 = win32net.NetUserGetInfo(None, str(user_info["name"]), 4)  # type: ignore[arg-type]
		user_info_4["password"] = user_info["password"]
		return user_info_4


class OpsiclientdNT5(OpsiclientdNT):
	def __init__(self):
		OpsiclientdNT.__init__(self)

	def shutdownMachine(self, waitSeconds=3):
		self._isShutdownTriggered = True
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested", 0)

		# Running in thread to avoid failure of shutdown (device not ready)
		ShutdownThread().start()

	def rebootMachine(self, waitSeconds=3):
		self._isRebootTriggered = True
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested", 0)

		# Running in thread to avoid failure of reboot (device not ready)
		RebootThread().start()


class ShutdownThread(threading.Thread):
	def __init__(self):
		threading.Thread.__init__(self, name="ShutdownThread")

	def run(self):
		while True:
			try:
				System.shutdown(0)
				logger.notice("Shutdown initiated")
				break
			except Exception as err:
				# Device not ready?
				logger.info("Failed to initiate shutdown: %s", err)
				time.sleep(1)


class RebootThread(threading.Thread):
	def __init__(self):
		threading.Thread.__init__(self, name="RebootThread")

	def run(self):
		while True:
			try:
				System.reboot(0)
				logger.notice("Reboot initiated")
				break
			except Exception as err:
				# Device not ready?
				logger.info("Failed to initiate reboot: %s", err)
				time.sleep(1)


class OpsiclientdNT6(OpsiclientdNT):
	def __init__(self):
		OpsiclientdNT.__init__(self)
