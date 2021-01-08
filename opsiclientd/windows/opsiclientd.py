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

# from Sens.h
SENSGUID_PUBLISHER = "{5fee1bd6-5b9b-11d1-8dd2-00aa004abd5e}"
SENSGUID_EVENTCLASS_LOGON = "{d5978630-5b9f-11d1-8dd2-00aa004abd5e}"

# from EventSys.h
PROGID_EventSystem = "EventSystem.EventSystem" # pylint: disable=invalid-name
PROGID_EventSubscription = "EventSystem.EventSubscription" # pylint: disable=invalid-name

IID_ISensLogon = "{d597bab3-5b9f-11d1-8dd2-00aa004abd5e}" # pylint: disable=invalid-name

wmi = None # pylint: disable=invalid-name
pythoncom = None # pylint: disable=invalid-name
importWmiAndPythoncomLock = threading.Lock()
def importWmiAndPythoncom(importWmi=True, importPythoncom=True):
	global wmi # pylint: disable=global-statement,invalid-name
	global pythoncom # pylint: disable=global-statement,invalid-name
	if importWmi and not pythoncom:
		importPythoncom = True

	if not ((wmi or not importWmi) and (pythoncom or not importPythoncom)):
		logger.info("Importing wmi / pythoncom")
		with importWmiAndPythoncomLock:
			while not ((wmi or not importWmi) and (pythoncom or not importPythoncom)):
				try:
					if not pythoncom and importPythoncom:
						logger.debug("Importing pythoncom")
						import pythoncom # pylint: disable=import-error,import-outside-toplevel,redefined-outer-name

					if not wmi and importWmi:
						logger.debug("Importing wmi")
						pythoncom.CoInitialize()
						try:
							import wmi # pylint: disable=import-error,import-outside-toplevel,redefined-outer-name
						finally:
							pythoncom.CoUninitialize()
				except Exception as import_error: # pylint: disable=broad-except
					logger.warning("Failed to import: %s, retrying in 2 seconds", import_error)
					time.sleep(2)

	return (wmi, pythoncom)

def opsiclientd_factory():
	windowsVersion = sys.getwindowsversion() # pylint: disable=no-member
	if windowsVersion.major == 5:  # NT5: XP
		return OpsiclientdNT5()
	elif windowsVersion.major >= 6:  # NT6: Vista / Windows7 and later
		return OpsiclientdNT6()
	raise Exception(f"Windows version {windowsVersion} not supported")


class OpsiclientdNT(Opsiclientd):
	def __init__(self):
		Opsiclientd.__init__(self)
		self._ms_update_installer = None

	def suspendBitlocker(self):
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
		except Exception as error: # pylint: disable=broad-except
			logger.warning("Failed to get shutdownRequested from registry: %s", error)
			shutdownRequested = 0

		logger.notice("Shutdown request in Registry: %s", shutdownRequested)
		return forceBool(shutdownRequested)

	def isWindowsInstallerBusy(self):
		if not self._ms_update_installer:
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

	def createOpsiSetupAdmin(self, delete_existing=False):
		# https://bugs.python.org/file46988/issue.py

		user_info = {
			"name": "opsisetupadmin",
			"full_name": "opsi setup admin",
			"comment": "auto created by opsi",
			"password": ''.join((random.choice(string.ascii_letters + string.digits) for i in range(12))),
			"priv": win32netcon.USER_PRIV_USER,
			"flags": win32netcon.UF_NORMAL_ACCOUNT | win32netcon.UF_SCRIPT | win32netcon.UF_DONT_EXPIRE_PASSWD
		}

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

		# Test if user exists
		user_exists = False
		try:
			win32net.NetUserGetInfo(None, user_info["name"], 1)
			user_exists = True
		except Exception: # pylint: disable=broad-except
			pass

		if user_exists:
			if delete_existing:
				# Delete user
				win32net.NetUserDel(None, user_info["name"])

				for pdir in glob.glob(f"c:\\users\\{user_info['name']}*"):
					try:
						subprocess.call(['takeown', '/d', 'Y', '/r', '/f', pdir])
						subprocess.call(['del', '/s', '/f', '/q',pdir], shell=True)
					except subprocess.CalledProcessError as rm_err:
						logger.warning("Failed to delete %s: %s", pdir, rm_err)
				user_exists = False
			else:
				# Update user password
				user_info_update = win32net.NetUserGetInfo(None, user_info["name"], 1)
				user_info_update["password"] = user_info["password"]
				win32net.NetUserSetInfo(None, user_info["name"], 1, user_info_update)

		if not user_exists:
			# Create user
			win32net.NetUserAdd(None, 1, user_info)

		sid = win32security.ConvertStringSidToSid("S-1-5-32-544")
		local_admin_group_name = win32security.LookupAccountSid(None, sid)[0]
		try:
			win32net.NetLocalGroupAddMembers(None, local_admin_group_name, 3, [{"domainandname": user_info["name"]}])
		except pywintypes.error as err:
			if err.winerror != 1378: # 1378 already a group member
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


class SensLogon(win32com.server.policy.DesignatedWrapPolicy):
	_com_interfaces_ = [IID_ISensLogon]
	_public_methods_ = [
		'Logon',
		'Logoff',
		'StartShell',
		'DisplayLock',
		'DisplayUnlock',
		'StartScreenSaver',
		'StopScreenSaver'
	]

	def __init__(self, callback):
		self._wrap_(self)
		self._callback = callback

	def subscribe(self):
		(_wmi, _pythoncom) = importWmiAndPythoncom(importWmi=False)

		subscription_interface = _pythoncom.WrapObject(self)

		event_system = win32com.client.Dispatch(PROGID_EventSystem)

		event_subscription = win32com.client.Dispatch(PROGID_EventSubscription)
		event_subscription.EventClassID = SENSGUID_EVENTCLASS_LOGON
		event_subscription.PublisherID = SENSGUID_PUBLISHER
		event_subscription.SubscriptionName = 'opsiclientd subscription'
		event_subscription.SubscriberInterface = subscription_interface

		event_system.Store(PROGID_EventSubscription, event_subscription)

	def Logon(self, *args): # pylint: disable=invalid-name
		logger.notice('Logon: %s', args)
		self._callback('Logon', *args)

	def Logoff(self, *args): # pylint: disable=invalid-name
		logger.notice('Logoff: %s', args)
		self._callback('Logoff', *args)

	def StartShell(self, *args): # pylint: disable=invalid-name
		logger.notice('StartShell: %s', args)
		self._callback('StartShell', *args)

	def DisplayLock(self, *args): # pylint: disable=invalid-name
		logger.notice('DisplayLock: %s', args)
		self._callback('DisplayLock', *args)

	def DisplayUnlock(self, *args): # pylint: disable=invalid-name
		logger.notice('DisplayUnlock: %s', args)
		self._callback('DisplayUnlock', *args)

	def StartScreenSaver(self, *args): # pylint: disable=invalid-name
		logger.notice('StartScreenSaver: %s', args)
		self._callback('StartScreenSaver', *args)

	def StopScreenSaver(self, *args): # pylint: disable=invalid-name
		logger.notice('StopScreenSaver: %s', args)
		self._callback('StopScreenSaver', *args)
