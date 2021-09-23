# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
import sys
import time
import threading
import subprocess
import glob
import random
import string

# pyright: reportMissingImports=false
import winreg # pylint: disable=import-error
import win32com.server.policy # pylint: disable=import-error
import win32com.client # pylint: disable=import-error
import win32netcon # pylint: disable=import-error
import win32net # pylint: disable=import-error
import win32security # pylint: disable=import-error
import pywintypes # pylint: disable=import-error

from OPSI.Types import forceBool
from OPSI import System

from opsicommon.logging import logger

from opsiclientd.Opsiclientd import Opsiclientd
from opsiclientd import config
from opsiclientd.Config import OPSI_SETUP_USER_NAME
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS

if not RUNNING_ON_WINDOWS:
	WindowsError = RuntimeError

def opsiclientd_factory():
	windowsVersion = sys.getwindowsversion() # pylint: disable=no-member
	if windowsVersion.major == 5:  # NT5: XP
		return OpsiclientdNT5()
	if windowsVersion.major >= 6:  # NT6: Vista / Windows7 and later
		return OpsiclientdNT6()
	raise Exception(f"Windows version {windowsVersion} not supported")


class OpsiclientdNT(Opsiclientd):
	def __init__(self):
		Opsiclientd.__init__(self)
		self._ms_update_installer = None

	def suspendBitlocker(self): # pylint: disable=no-self-use
		logger.notice("Suspending bitlocker for one reboot if active")
		try:
			System.execute(
				"powershell.exe -ExecutionPolicy Bypass -Command \""
				"foreach($v in Get-BitLockerVolume)"
				"{if ($v.EncryptionPercentage -gt 0)"
				"{$v | Suspend-BitLocker -RebootCount 1}}\"",
				captureStderr=True,
				waitForEnding=True,
				timeout=20
			)
		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to suspend bitlocker: %s", err, exc_info=True)

	def rebootMachine(self, waitSeconds=3):
		if config.get('global', 'suspend_bitlocker_on_reboot'):
			windowsVersion = sys.getwindowsversion() # pylint: disable=no-member
			if (windowsVersion.major == 6 and windowsVersion.minor >= 4) or windowsVersion.major > 6: # Win10 and later
				self.suspendBitlocker()
		super().rebootMachine(waitSeconds)

	def clearRebootRequest(self):
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested", 0)

	def clearShutdownRequest(self):
		System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "ShutdownRequested", 0)

	def isRebootRequested(self):
		try:
			rebootRequested = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\winst", "RebootRequested")
		except Exception as error: # pylint: disable=broad-except
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
		except Exception as err: # pylint: disable=broad-except
			logger.info("Failed to get shutdownRequested from registry: %s", err)
			shutdownRequested = 0

		logger.notice("Shutdown request in Registry: %s", shutdownRequested)
		return forceBool(shutdownRequested)

	def isWindowsInstallerBusy(self):
		if not self._ms_update_installer:
			from opsiclientd.windows import importWmiAndPythoncom # pylint: disable=import-outside-toplevel
			(_wmi, _pythoncom) = importWmiAndPythoncom(
				importWmi=False,
				importPythoncom=True
			)
			_pythoncom.CoInitialize()
			session = win32com.client.Dispatch("Microsoft.Update.Session")
			self._ms_update_installer = session.CreateUpdateInstaller()
		return self._ms_update_installer.isBusy

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
			if not response.get("error") and response.get("result"):
				return True
			raise RuntimeError(f"opsi credential provider failed to login user '{username}': {response.get('error')}")

	def cleanup_opsi_setup_user(self, keep_sid: str = None):  # pylint: disable=no-self-use,too-many-locals
		keep_profile = None
		with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList") as key:
			for idx in range(1024):
				try:
					keyname = winreg.EnumKey(key, idx)
					with winreg.OpenKey(key, keyname) as subkey:
						profile_path = winreg.QueryValueEx(subkey, "ProfileImagePath")[0]
						if keep_sid and keyname == keep_sid:
							keep_profile = profile_path
							continue
					username = profile_path.split("\\")[-1].split(".")[0]
					if not username.startswith(OPSI_SETUP_USER_NAME):
						continue
					sid = win32security.ConvertStringSidToSid(keyname)
					try:
						#win32profile.DeleteProfile(sid)
						username, _domain, _type = win32security.LookupAccountSid(None, sid)
						logger.info("Deleting user '%s'", username)
						win32net.NetUserDel(None, username)
					except Exception:  # pylint: disable=broad-except
						pass
					logger.info("Deleting '%s' from ProfileList", keyname)
				except WindowsError as err:
					if err.errno == 22:  # pylint: disable=no-member
						# No more subkeys
						break
					logger.debug(err)

		# takeown parameter /d is localized 😠
		res = subprocess.run("choice <nul 2>nul", capture_output=True, check=False, shell=True)
		yes = res.stdout.decode().split(",")[0].lstrip("[").strip()
		for pdir in glob.glob(f"c:\\users\\{OPSI_SETUP_USER_NAME}*"):
			if keep_profile and keep_profile.lower() == pdir.lower():
				continue
			logger.info("Deleting user dir '%s'", pdir)
			for cmd, exit_codes_success in (
				(['takeown', '/d', yes, '/r', '/f', pdir], [0, 1]),
				(['powershell.exe', '-ExecutionPolicy', 'Bypass', '-Command', f'Remove-Item -Recurse -Force "{pdir}"'], [0])
			):
				logger.info("Executing: %s", cmd)
				res = subprocess.run(cmd, capture_output=True, check=False)
				out = res.stdout.decode(errors="replace") + res.stderr.decode(errors="replace")
				if res.returncode not in exit_codes_success:
					logger.warning("Command %s failed with exit code %s: %s", cmd, res.returncode, out)
				else:
					logger.info("Command %s successful: %s", cmd, out)

	def createOpsiSetupUser(self, admin=True, delete_existing=False): # pylint: disable=no-self-use,too-many-branches
		# https://bugs.python.org/file46988/issue.py

		user_info = {
			"name": OPSI_SETUP_USER_NAME,
			"full_name": "opsi setup user",
			"comment": "auto created by opsi",
			"password": f"/{''.join((random.choice(string.ascii_letters + string.digits) for i in range(8)))}?",
			"priv": win32netcon.USER_PRIV_USER,
			"flags": win32netcon.UF_NORMAL_ACCOUNT | win32netcon.UF_SCRIPT | win32netcon.UF_DONT_EXPIRE_PASSWD
		}

		# Test if user exists
		user_sid = None
		try:
			win32net.NetUserGetInfo(None, user_info["name"], 1)
			user_sid = win32security.ConvertSidToStringSid(
				win32security.LookupAccountName(None, user_info["name"])[0]
			)
			logger.info("User '%s' exists, sid is '%s'", user_info["name"], user_sid)
		except Exception: # pylint: disable=broad-except
			pass

		self.cleanup_opsi_setup_user(keep_sid=None if delete_existing else user_sid)
		if delete_existing:
			user_sid = None

		# Hide user from login
		try:
			winreg.CreateKeyEx(
				winreg.HKEY_LOCAL_MACHINE,
				r'Software\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts',
				0,
				winreg.KEY_WOW64_64KEY | winreg.KEY_ALL_ACCESS # sysnative
			)
		except WindowsError: # pylint: disable=undefined-variable
			pass
		try:
			winreg.CreateKeyEx(
				winreg.HKEY_LOCAL_MACHINE,
				r'Software\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList',
				0,
				winreg.KEY_WOW64_64KEY | winreg.KEY_ALL_ACCESS # sysnative
			)
		except WindowsError: # pylint: disable=undefined-variable
			pass

		with winreg.OpenKey(
			winreg.HKEY_LOCAL_MACHINE,
			r'Software\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList',
			0,
			winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY # sysnative
		) as reg_key:
			winreg.SetValueEx(reg_key, user_info["name"], 0, winreg.REG_DWORD, 0)

		if user_sid:
			logger.info("Updating password of user '%s'", user_info["name"])
			user_info_update = win32net.NetUserGetInfo(None, user_info["name"], 1)
			user_info_update["password"] = user_info["password"]
			win32net.NetUserSetInfo(None, user_info["name"], 1, user_info_update)
		else:
			logger.info("Creating user '%s'", user_info["name"])
			win32net.NetUserAdd(None, 1, user_info)

		local_admin_group_sid = win32security.ConvertStringSidToSid("S-1-5-32-544")
		local_admin_group_name = win32security.LookupAccountSid(None, local_admin_group_sid)[0]
		try:
			if admin:
				logger.info("Adding user '%s' to admin group", user_info["name"])
				win32net.NetLocalGroupAddMembers(None, local_admin_group_name, 3, [{"domainandname": user_info["name"]}])
			else:
				logger.info("Removing user '%s' from admin group", user_info["name"])
				win32net.NetLocalGroupDelMembers(None, local_admin_group_name, [user_info["name"]])
		except pywintypes.error as err:
			# 1377 - ERROR_MEMBER_NOT_IN_ALIAS
			#  The specified account name is not a member of the group.
			# 1378 # ERROR_MEMBER_IN_ALIAS
			#  The specified account name is already a member of the group.
			if err.winerror not in (1377, 1378):
				raise

		user_info_4 = win32net.NetUserGetInfo(None, user_info["name"], 4)
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
		threading.Thread.__init__(self)

	def run(self):
		while True:
			try:
				System.shutdown(0)
				logger.notice("Shutdown initiated")
				break
			except Exception as err: # pylint: disable=broad-except
				# Device not ready?
				logger.info("Failed to initiate shutdown: %s", err)
				time.sleep(1)


class RebootThread(threading.Thread):
	def __init__(self):
		threading.Thread.__init__(self)

	def run(self):
		while True:
			try:
				System.reboot(0)
				logger.notice("Reboot initiated")
				break
			except Exception as err: # pylint: disable=broad-except
				# Device not ready?
				logger.info("Failed to initiate reboot: %s", err)
				time.sleep(1)


class OpsiclientdNT6(OpsiclientdNT):
	def __init__(self):
		OpsiclientdNT.__init__(self)
