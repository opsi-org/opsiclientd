# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
Configuring opsiclientd.
"""

from __future__ import annotations

import os
import platform
import re
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import netifaces  # type: ignore[import]
from OPSI import System  # type: ignore[import]
from OPSI.Backend.JSONRPC import JSONRPCBackend  # type: ignore[import]
from OPSI.Util import blowfishDecrypt, objectToBeautifiedText  # type: ignore[import]
from OPSI.Util.File import IniFile  # type: ignore[import]
from opsicommon.client.opsiservice import ServiceClient, ServiceVerificationFlags
from opsicommon.logging import LOG_NOTICE, get_logger, logging_config, secret_filter
from opsicommon.types import (
	forceBool,
	forceHostId,
	forceList,
	forceProductIdList,
	forceUnicode,
	forceUnicodeList,
)
from opsicommon.utils import Singleton

from opsiclientd.SystemCheck import (
	RUNNING_ON_DARWIN,
	RUNNING_ON_LINUX,
	RUNNING_ON_MACOS,
	RUNNING_ON_WINDOWS,
)

if TYPE_CHECKING:
	from opsicommon.objects import OpsiDepotserver

	from opsiclientd.Events.Basic import Event

# It is possible to set multiple certificates as UIB_OPSI_CA
UIB_OPSI_CA = """-----BEGIN CERTIFICATE-----
MIIFvjCCA6agAwIBAgIWb3BzaS11aWItY2EtMjE1NzMwODcwNzANBgkqhkiG9w0B
AQsFADB+MQswCQYDVQQGEwJERTELMAkGA1UECAwCUlAxDjAMBgNVBAcMBU1haW56
MREwDwYDVQQKDAh1aWIgR21iSDENMAsGA1UECwwEb3BzaTEUMBIGA1UEAwwLdWli
IG9wc2kgQ0ExGjAYBgkqhkiG9w0BCQEWC2luZm9AdWliLmRlMB4XDTIxMDIyNjEy
NTMxNloXDTQ4MDcxNDEyNTMxNlowfjELMAkGA1UEBhMCREUxCzAJBgNVBAgMAlJQ
MQ4wDAYDVQQHDAVNYWluejERMA8GA1UECgwIdWliIEdtYkgxDTALBgNVBAsMBG9w
c2kxFDASBgNVBAMMC3VpYiBvcHNpIENBMRowGAYJKoZIhvcNAQkBFgtpbmZvQHVp
Yi5kZTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBALJn/XO2KV8Ax9I2
5PcaN13kat8Y7xB0MVrU64iwLtoYSjayQ62tcmcJNBQeo6x4COQdp3XQTvy7fCjS
y6O9WwySr920Wh2/etZkXNA6qgqqLBSx6hw8zCGXPLuxkT/INvFVr3zWaH4Irx2o
SB94cPvvM3mnp3vhhphBDJUKqIvm7uz2h5npMVD0UJCeLhcG9iBe7FcRT3xaUDmi
QDE5norGK2YS/kvMv1lGAxcoM8dJ3Dl0hAn6mFKJ7lIBzojxSuNQuBMZlx7OsCbS
p0u4dGR82LYTX2RZvZOJIQPEn+XzsyNG/2vHjlnVDLUikrdRs3IJ8pJQyIAOF1aq
tb5X4K/Syy8OIV71++hvnksEiI2JgBti6IdFgHVCb034hHhzblQdwZeRsQXy5b6X
ZibrRkhkoRXptHkLb3Qt3yvi1xtmvR5le5Jh7AczjTYVAx0EToEq2WLZFyhTgQgH
0PZthUeb0q9fBUZoqpppePBU+BnKvVga8hRpVapx4gy7Ms6SaHMZhKVR7aBAAbmb
IhCWJ3dQPbWa/De8JC5SaEQMWyg+UPD+6N8EZXIsAXczqjnSLfbfXBHlPrfxVVOD
YtvhNaSchyXjXEpCqXrTJtYrxQ3m7YGXfs8+P7Ncbl2py7bvYKBl1c7KeqJctUgK
vu6ym8XjsMWSK/YZABCNB4dL6mOTAgMBAAGjMjAwMB0GA1UdDgQWBBTpzwF8edXy
f1RBXkqReeeCTKvrpTAPBgNVHRMBAf8EBTADAQH/MA0GCSqGSIb3DQEBCwUAA4IC
AQCgLNQiM70eW7yc0Jrnklwm8euWh5s7iVr9hCaM8LaYXrk1LY04W4WpQPyk0CnW
jlwbsSfvksc65HwkK7W2M/CGo98Dc9bgLvhDRa90+18ktiF54TlTRy1DeGEfxcF0
CAEqWMcSTxkaMdWEI/DlWmwKlHmH+NyoajA/iJq+0yMr8TKIKmIoX0f7TuXiiPM+
roWG814e5dvapr3rYE5m6sf7kjVufaTEHWogo5oFHtXzTA04L51ZBvZl09isN+OK
eD0dL26/rdTiLOetGnta5BX0Rt1Ua4xUQPxgxVS70n9SN5gSo3LKEMAVRZvF56xz
mcDrJFQM6pEJ/uoH5cJe+EL0YMGndrKPeXFrIhdY64R4WY/iGNFXl0EOL2SX0M81
D+CAXzvO0SPjJLTrYIfpBqq0LaPAv6V5JlwpW27BL4jdmc9ADj9c4nPRzXU6d1Tb
6avQ4OyVgU/wUoUwq6AsO2BMVmfu5JS02Phl+WG7T+CR7HigNjr5nRJk2HayJ+z1
6HIb8KmSqzTt+5VuwSkMLDdUXVt2Dok9dzKYFufWvrvDnZnz0svDwToQ9LAjXFij
igDA0os9lNV7Pn4nlK0c+Fk/2+wZdF4rzl0Bia4C6CMso0M+3Kqe7aqY6+/I6jgy
kGOsCMSImzajpmtonx3ccPgSOyEWyoEaGij6u80QtFkj9g==
-----END CERTIFICATE-----"""

OPSI_SETUP_USER_NAME = "opsisetupuser"

logger = get_logger()


@dataclass
class RestartMarkerConfig:
	disabled_event_types: list[str] = field(default_factory=list)
	run_opsi_script: str | None = None
	product_id: str | None = None
	restart_service: bool = True
	remove_marker: bool = True

	def __post_init__(self) -> None:
		if self.disabled_event_types:
			self.disabled_event_types = [v.strip().lower() for v in self.disabled_event_types if v.strip()]
		if self.product_id:
			self.product_id = self.product_id.strip().lower()


class SectionNotFoundException(ValueError):
	pass


class NoConfigOptionFoundException(ValueError):
	pass


class Config(metaclass=Singleton):
	_initialized = False
	WINDOWS_DEFAULT_PATHS = {
		"global": {
			"tmp_dir": "c:\\opsi.org\\tmp",
			"log_dir": "c:\\opsi.org\\log",
			"state_file": "c:\\opsi.org\\opsiclientd\\state.json",
			"timeline_db": "c:\\opsi.org\\opsiclientd\\timeline.sqlite",
			"server_cert_dir": "c:\\opsi.org\\tls",
		},
		"cache_service": {"storage_dir": "c:\\opsi.org\\cache"},
		"control_server": {"files_dir": "c:\\opsi.org\\opsi-client-agent\\files"},
	}

	LINUX_DEFAULT_PATHS = {
		"global": {
			"tmp_dir": "/tmp",
			"log_dir": "/var/log/opsi-client-agent",
			"config_file": "/etc/opsi-client-agent/opsiclientd.conf",
			"state_file": "/var/lib/opsi-client-agent/opsiclientd/state.json",
			"timeline_db": "/var/lib/opsi-client-agent/opsiclientd/timeline.sqlite",
			"server_cert_dir": "/etc/opsi-client-agent/tls",
		},
		"control_server": {
			"ssl_server_key_file": "/etc/opsi-client-agent/opsiclientd.pem",
			"ssl_server_cert_file": "/etc/opsi-client-agent/opsiclientd.pem",
			"static_dir": "/usr/share/opsi-client-agent/opsiclientd/static_html",
			"files_dir": "/var/local/share/opsi-client-agent/files",
		},
		"cache_service": {"storage_dir": "/var/cache/opsi-client-agent"},
		"depot_server": {"drive": "/media/opsi_depot"},
	}

	MACOS_DEFAULT_PATHS = {
		"global": {
			"tmp_dir": "/tmp",
			"log_dir": "/var/log/opsi-client-agent",
			"config_file": "/etc/opsi-client-agent/opsiclientd.conf",
			"state_file": "/var/lib/opsi-client-agent/opsiclientd/state.json",
			"timeline_db": "/var/lib/opsi-client-agent/opsiclientd/timeline.sqlite",
			"server_cert_dir": "/etc/opsi-client-agent/tls",
		},
		"control_server": {
			"ssl_server_key_file": "/etc/opsi-client-agent/opsiclientd.pem",
			"ssl_server_cert_file": "/etc/opsi-client-agent/opsiclientd.pem",
			"static_dir": "/usr/local/share/opsi-client-agent/opsiclientd/static_html",
			"files_dir": "/var/local/share/opsi-client-agent/files",
		},
		"cache_service": {"storage_dir": "/var/cache/opsi-client-agent"},
		"depot_server": {"drive": "/private/var/opsisetupadmin/opsi_depot"},
	}

	def __init__(self) -> None:
		if self._initialized:
			return
		self._initialized = True

		baseDir = self.getBaseDirectory()

		self._temporaryConfigServiceUrls: list[str] = []
		self._temporaryDepotDrive: str | None = None
		self._temporary_depot_path: str | None = None
		self._config_file_mtime: float = 0.0
		self.disabledEventTypes: list[str] = []

		self._config = {
			"system": {
				"program_files_dir": "",
			},
			"global": {
				"base_dir": baseDir,
				"config_file": os.path.join(baseDir, "opsiclientd", "opsiclientd.conf"),
				"log_file": "opsiclientd.log",
				"log_level": LOG_NOTICE,
				"keep_rotated_logs": 10,
				"max_log_size": 5.0,  # In MB
				"max_log_transfer_size": 5.0,  # In MB
				"host_id": System.getFQDN().lower(),
				"opsi_host_key": "",
				"wait_for_gui_timeout": 120,
				"block_login_notifier": "",
				"verify_server_cert": False,
				"verify_server_cert_by_ca": False,
				"trust_uib_opsi_ca": True,
				"replace_expired_ca": True,
				"install_opsi_ca_into_os_store": False,
				"proxy_url": "system",
				"suspend_bitlocker_on_reboot": False,
				"ip_version": "auto",
				"tmp_dir_cleanup": False,
				"post_trusted_installer_delay": 15,
				"message_of_the_day_enabled": False,
			},
			"config_service": {
				"url": [],
				"compression": True,
				"connection_timeout": 10,
				"user_cancelable_after": 0,
				"sync_time_from_service": False,
				"permanent_connection": False,
				"reconnect_wait_min": 5,
				"reconnect_wait_max": 120,
			},
			"depot_server": {
				# The id of the depot the client is assigned to
				"master_depot_id": "",
				# The id of the depot currently set as (dynamic) depot
				"depot_id": "",
				"url": "",
				"drive": "",
				"username": "pcpatch",
			},
			"cache_service": {
				"product_cache_max_size": 6000000000,
				"extension_config_dir": "",
				"include_product_group_ids": [],
				"exclude_product_group_ids": [],
				"sync_products_with_actions_only": True,
			},
			"control_server": {
				"interface": ["0.0.0.0", "::"],
				"port": 4441,
				"ssl_server_key_file": os.path.join(baseDir, "opsiclientd", "opsiclientd.pem"),
				"ssl_server_cert_file": os.path.join(baseDir, "opsiclientd", "opsiclientd.pem"),
				"static_dir": os.path.join(baseDir, "opsiclientd", "static_html"),
				"max_authentication_failures": 5,
				"kiosk_api_active": True,
				"process_actions_event": "auto",
				"skip_setup_firewall": False,
				"start_delay": 0,
			},
			"notification_server": {
				"interface": ["127.0.0.1", "::1"],
				"start_port": 44000,
				"popup_port": 45000,
				"start_delay": 0,
			},
			"opsiclientd_rpc": {
				"command": "",
			},
			"opsiclientd_notifier": {
				"command": "",
				"alt_command": "",
				"alt_ids": [],
				"product_info": "{id}",
			},
			"action_processor": {
				"local_dir": "",
				"remote_dir": "",
				"remote_common_dir": "",
				"filename": "",
				"command": "",
				"run_as_user": "SYSTEM",
				"create_user": True,
				"delete_user": True,
				"create_environment": False,
			},
		}

		self._applySystemSpecificConfiguration()

	@staticmethod
	def getBaseDirectory() -> str:
		if RUNNING_ON_WINDOWS:
			pfp = os.environ.get("PROGRAMFILES(X86)", os.environ.get("PROGRAMFILES", "c:\\Program Files"))
			baseDir = os.path.join(pfp, "opsi.org", "opsi-client-agent")
			if not os.path.exists(baseDir):
				try:
					baseDir = os.path.abspath(os.path.dirname(sys.argv[0]))
				except Exception:
					baseDir = "."
		elif RUNNING_ON_MACOS:
			baseDir = os.path.join("/usr", "local", "lib", "opsi-client-agent")
		else:
			baseDir = os.path.join("/usr", "lib", "opsi-client-agent")

		return baseDir

	@property
	def restart_marker(self) -> str:
		if RUNNING_ON_WINDOWS:
			# Old location of restart marker
			old_location = os.path.join(os.path.dirname(sys.argv[0]), ".opsiclientd_restart")
			if os.path.exists(old_location):
				return old_location
		return os.path.join(self.getBaseDirectory(), ".opsiclientd_restart")

	def check_restart_marker(self) -> RestartMarkerConfig | None:
		logger.info("Checking if restart marker '%s' exists", self.restart_marker)
		if not os.path.exists(self.restart_marker):
			return None

		resm_config = RestartMarkerConfig()
		if os.path.getsize(self.restart_marker) == 0:
			logger.notice("Old restart marker found, gui startup and daemon startup events disabled")
			resm_config.disabled_event_types = ["gui startup", "daemon startup"]
			resm_config.remove_marker = True
		else:
			logger.notice("Reading restart marker")
			with open(self.restart_marker, "r", encoding="utf-8") as file:
				for line in file.readlines():
					line = line.strip()
					if line.startswith("#") or "=" not in line:
						continue
					option, value = line.split("=", 1)
					option = option.strip().lower()
					if option == "disabled_event_types":
						resm_config.disabled_event_types = [v.strip().lower() for v in value.split(",") if v.strip()]
					elif option == "run_opsi_script":
						resm_config.run_opsi_script = value
						if "," in value:
							resm_config.product_id, resm_config.run_opsi_script = value.split(",", 1)
						resm_config.product_id = resm_config.product_id.strip().lower() if resm_config.product_id else None
						resm_config.run_opsi_script = resm_config.run_opsi_script.strip()
						resm_config.disabled_event_types = ["gui startup", "daemon startup"]
					elif option == "remove_marker":
						resm_config.remove_marker = forceBool(value)
					elif option == "restart_service":
						resm_config.restart_service = forceBool(value)

		logger.notice("Restart marker config: %r", resm_config)
		if resm_config.disabled_event_types:
			self.disabledEventTypes = resm_config.disabled_event_types
		if resm_config.remove_marker or resm_config.restart_service:
			try:
				os.remove(self.restart_marker)
			except Exception as err:
				logger.error(err)
		return resm_config

	def _applySystemSpecificConfiguration(self) -> None:
		defaultToApply = self.WINDOWS_DEFAULT_PATHS.copy()
		if RUNNING_ON_LINUX:
			defaultToApply = self.LINUX_DEFAULT_PATHS.copy()
		elif RUNNING_ON_DARWIN:
			defaultToApply = self.MACOS_DEFAULT_PATHS.copy()

		baseDir = self._config["global"]["base_dir"]

		for key in list(self._config):
			if key in defaultToApply:
				self._config[key].update(defaultToApply[key])

		self._config["cache_service"]["extension_config_dir"] = os.path.join(baseDir, "opsiclientd", "extend.d")

		if sys.platform == "win32":
			systemDrive = System.getSystemDrive()
			logger.debug("Running on windows: adapting paths to use system drive (%s)", systemDrive)
			systemDrive += "\\"
			self._config["cache_service"]["storage_dir"] = os.path.join(systemDrive, "opsi.org", "cache")
			self._config["global"]["config_file"] = os.path.join(baseDir, "opsiclientd", "opsiclientd.conf")
			self._config["global"]["log_dir"] = os.path.join(systemDrive, "opsi.org", "log")
			self._config["global"]["state_file"] = os.path.join(systemDrive, "opsi.org", "opsiclientd", "state.json")
			self._config["global"]["server_cert_dir"] = os.path.join(systemDrive, "opsi.org", "tls")
			self._config["global"]["timeline_db"] = os.path.join(systemDrive, "opsi.org", "opsiclientd", "timeline.sqlite")
			self._config["system"]["program_files_dir"] = System.getProgramFilesDir()

			if sys.getwindowsversion()[0] == 5:
				self._config["action_processor"]["run_as_user"] = "pcpatch"
		else:
			sslCertDir = os.path.join("/etc", "opsi-client-agent")

			for certPath in ("ssl_server_key_file", "ssl_server_cert_file"):
				if sslCertDir not in self._config["control_server"][certPath]:
					self._config["control_server"][certPath] = os.path.join(sslCertDir, self._config["control_server"][certPath])

	def getDict(self) -> dict[str, Any]:
		return self._config

	def has_option(self, section: str, option: str) -> bool:
		if section not in self._config:
			return False
		if option not in self._config[section]:
			return False
		return True

	def del_option(self, section: str, option: str) -> None:
		del self._config[section][option]

	def get(self, section: str, option: str, raw: bool = False) -> Any:
		if not section:
			section = "global"

		section = str(section).lower().strip()
		option = str(option).lower().strip()
		if section not in self._config:
			raise SectionNotFoundException(f"No such config section: {section}")
		if option not in self._config[section]:
			raise NoConfigOptionFoundException(f"No such config option in section '{section}': {option}")

		value = self._config[section][option]
		if not raw and isinstance(value, str) and (value.count("%") >= 2):
			value = self.replace(value)
		if isinstance(value, str):
			value = forceUnicode(value)
		return value

	@property
	def ca_cert_file(self) -> str:
		cert_dir = self.get("global", "server_cert_dir")
		return os.path.join(cert_dir, "opsi-ca-cert.pem")

	@property
	def service_verification_flags(self) -> list[ServiceVerificationFlags]:
		# Do not verify certificate but fetch opsi CA
		verify = [ServiceVerificationFlags.ACCEPT_ALL, ServiceVerificationFlags.OPSI_CA]
		if self.get("global", "verify_server_cert"):
			# Verify certificate if local CA exists and fetch opsi CA
			verify = [ServiceVerificationFlags.OPSI_CA]
			if self.get("global", "trust_uib_opsi_ca"):
				verify.append(ServiceVerificationFlags.UIB_OPSI_CA)
			if self.get("global", "replace_expired_ca"):
				verify.append(ServiceVerificationFlags.REPLACE_EXPIRED_CA)
		return verify

	@property
	def action_processor_name(self) -> str:
		if "opsi-winst" in self.get("action_processor", "local_dir"):
			return "opsi-winst"
		return "opsi-script"

	def set(self, section: str, option: str, value: Any) -> None:
		if not section:
			section = "global"

		section = str(section).strip().lower()
		if section == "system":
			return

		option = str(option).strip().lower()
		if isinstance(value, str):
			value = value.strip()

		# Rename legacy options
		if option == "warning_time":
			option = "action_warning_time"
		elif option == "user_cancelable":
			option = "action_user_cancelable"
		elif option == "w10bitlockersuspendonreboot":
			option = "suspend_bitlocker_on_reboot"

		# Check if empty value is allowed
		if (
			value == ""
			and "command" not in option
			and "productids" not in option
			and "exclude_product_group_ids" not in option
			and "include_product_group_ids" not in option
			and "proxy_url" not in option
			and "working_window" not in option
			and "alt_ids" not in option
		):
			if section == "action_processor" and option == "remote_common_dir":
				return
			logger.warning("Refusing to set empty value config %s.%s", section, option)
			return

		if section == "depot_server" and option == "drive":
			if (RUNNING_ON_LINUX or RUNNING_ON_DARWIN) and not value.startswith("/"):
				logger.warning("Refusing to set %s.%s to '%s' on posix", section, option, value)
				return

		# Preprocess values, convert to correct type
		if option in ("exclude_product_group_ids", "include_product_group_ids", "alt_ids", "interface"):
			if not isinstance(value, list):
				value = [x.strip() for x in value.split(",") if x.strip()]
			value = forceList(value)

		if RUNNING_ON_WINDOWS and (option.endswith("_dir") or option.endswith("_file")):
			if ":" in value and ":\\" not in value:
				logger.warning("Correcting path '%s' to '%s'", value, value.replace(":", ":\\"))
				value = value.replace(":", ":\\")

		if option.endswith("_dir") or option.endswith("_file"):
			arch = "64" if "64" in platform.architecture()[0] else "32"
			value = value.replace("%arch%", arch)

		if section.startswith("event_") or section.startswith("precondition_"):
			if option.endswith("_warning_time") or option.endswith("_user_cancelable"):
				try:
					value = int(value)
				except ValueError:
					value = 0
			elif option in ("active",):
				value = forceBool(value)

		elif section in self._config and option in self._config[section]:
			if section == "config_service" and option == "url":
				urls = value
				if not isinstance(urls, list):
					urls = str(urls).split(",")

				value = []
				for url in urls:
					url = url.strip()
					if not re.search("https?://[^/]+", url):
						logger.error("Bad config service url '%s'", url)
					if url not in value:
						value.append(url)
			else:
				try:
					if isinstance(self._config[section][option], bool):
						value = forceBool(value)
					elif self._config[section][option] is not None:
						_type = type(self._config[section][option])
						value = _type(value)
				except ValueError as err:
					logger.error("Failed to set value '%s' for config %s.%s: %s", value, section, option, err)
					return

				# Check / correct value
				if option in ("connection_timeout", "user_cancelable_after") and value < 0:
					value = 0
				elif option == "opsi_host_key":
					if len(value) != 32:
						raise ValueError("Bad opsi host key, length != 32")
					secret_filter.add_secrets(value)
				elif option in ("depot_id", "host_id"):
					value = forceHostId(value.replace("_", "-"))

		else:
			logger.warning("Refusing to set value '%s' for invalid config %s.%s", value, section, option)
			return

		logger.info("Setting config %s.%s to %r", section, option, value)

		if section not in self._config:
			self._config[section] = {}
		self._config[section][option] = value

		if section == "global" and option == "log_level":
			logging_config(file_level=self._config[section][option])

	def replace(self, string: str, escaped: bool = False) -> str:
		for section, values in self._config.items():
			if not isinstance(values, dict):
				continue
			for key, value in values.items():
				value = forceUnicode(value)
				if string.find('"%' + forceUnicode(section) + "." + forceUnicode(key) + '%"') != -1 and escaped:
					if os.name == "posix":
						value = value.replace('"', '\\"')
					elif RUNNING_ON_WINDOWS:
						value = value.replace('"', '^"')
				newString = string.replace("%" + forceUnicode(section) + "." + forceUnicode(key) + "%", value)

				if newString != string:
					string = self.replace(newString, escaped)
		return forceUnicode(string)

	def readConfigFile(self) -> None:
		"""Get settings from config file"""
		logger.notice("Trying to read config from file: '%s'", self.get("global", "config_file"))

		try:
			self._config_file_mtime = os.path.getmtime(self.get("global", "config_file"))
			# Read Config-File
			config = IniFile(filename=self.get("global", "config_file"), raw=True).parse()

			# Read log settings early
			if config.has_section("global") and config.has_option("global", "log_level"):
				self.set("global", "log_level", config.get("global", "log_level"))

			for section in config.sections():
				logger.debug("Processing section '%s' in config file: '%s'", section, self.get("global", "config_file"))

				for option, value in config.items(section):
					if section == "global" and option == "log_dir":
						continue  # Ingoring configured log_dir

					option = option.lower()
					self.set(section.lower(), option, value)
		except Exception as err:
			# An error occured while trying to read the config file
			logger.error("Failed to read config file '%s': %s", self.get("global", "config_file"), err)
			logger.error(err, exc_info=True)
			return

		if not self.get("depot_server", "master_depot_id"):
			self.set("depot_server", "master_depot_id", self.get("depot_server", "depot_id"))

		self.set("control_server", "static_dir", self.get("control_server", "static_dir").replace("/", os.sep))

		logger.notice("Config read")
		logger.debug("Config is now:\n %s", objectToBeautifiedText(self._config))

	def updateConfigFile(self, force: bool = False) -> None:
		logger.info("Updating config file: '%s'", self.get("global", "config_file"))

		if self._config_file_mtime and os.path.getmtime(self.get("global", "config_file")) > self._config_file_mtime:
			msg = "overwriting changes is forced" if force else "keeping file as is"
			logger.warning("The config file '%s' has been changed by another program, %s", self.get("global", "config_file"), msg)
			if not force:
				return

		try:
			configFile = IniFile(filename=self.get("global", "config_file"), raw=True)
			configFile.setKeepOrdering(True)
			(config, comments) = configFile.parse(returnComments=True)
			changed = False
			for section, values in self._config.items():
				if not isinstance(values, dict):
					continue
				if section == "system":
					continue
				if not config.has_section(section):
					logger.debug("Config changed - new section: %s", section)
					config.add_section(section)
					changed = True

				for option, value in values.items():
					if (section == "global") and (option == "config_file"):
						# Do not store these option
						continue
					if isinstance(value, list):
						value = ", ".join(forceUnicodeList(value))
					elif isinstance(value, bool):
						value = str(value).lower()
					else:
						value = forceUnicode(value)

					if value.lower() in ("true", "false"):
						value = value.lower()

					if not config.has_option(section, option):
						logger.debug("Config changed - new option: %s.%s = %s", section, option, value)
						config.set(section, option, value)
						changed = True
					elif config.get(section, option) != value:
						logger.debug(
							"Config changed - changed value: %s.%s = %s => %s", section, option, config.get(section, option), value
						)
						config.set(section, option, value)
						changed = True

				for option in config.options(section):
					if option not in values:
						logger.info("Removing obsolete config option: %s.%s", section, option)
						config.remove_option(section, option)
						changed = True

			if changed:
				# Write back config file if changed
				configFile.generate(config, comments=comments)
				logger.notice("Config file '%s' written", self.get("global", "config_file"))
				self._config_file_mtime = os.path.getmtime(self.get("global", "config_file"))
			else:
				logger.info("No need to write config file '%s', config file is up to date", self.get("global", "config_file"))
		except Exception as err:
			# An error occured while trying to write the config file
			logger.error(err, exc_info=True)
			logger.error("Failed to write config file '%s': %s", self.get("global", "config_file"), err)

	def setTemporaryDepotDrive(self, temporaryDepotDrive: str | None) -> None:
		self._temporaryDepotDrive = temporaryDepotDrive

	def getDepotDrive(self) -> str:
		if self._temporaryDepotDrive:
			return self._temporaryDepotDrive
		return self.get("depot_server", "drive")

	def set_temporary_depot_path(self, path: str | None) -> None:
		self._temporary_depot_path = path

	def get_depot_path(self) -> str:
		if self._temporary_depot_path:
			return self._temporary_depot_path
		return self.get("depot_server", "drive")

	def setTemporaryConfigServiceUrls(self, temporaryConfigServiceUrls: list[str]) -> None:
		self._temporaryConfigServiceUrls = forceList(temporaryConfigServiceUrls)

	def getConfigServiceUrls(self, allowTemporaryConfigServiceUrls: bool = True) -> list[str]:
		if allowTemporaryConfigServiceUrls and self._temporaryConfigServiceUrls:
			return self._temporaryConfigServiceUrls

		return self.get("config_service", "url")

	def getDepot(
		self,
		configService: JSONRPCBackend,
		event: Event | None = None,
		productIds: list[str] | None = None,
		masterOnly: bool = False,
		forceDepotProtocol: str | None = None,
	) -> tuple[OpsiDepotserver, str]:
		productIds = forceProductIdList(productIds or [])
		if not configService:
			raise RuntimeError("Not connected to config service")

		selectedDepot = None

		depotIds = []
		dynamicDepot = False
		depotProtocol = "cifs"
		if forceDepotProtocol:
			depotProtocol = forceDepotProtocol

		config_ids = ["clientconfig.depot.dynamic", "clientconfig.depot.protocol", "opsiclientd.depot_server.depot_id"]
		config_states = {}
		if hasattr(configService, "configState_getValues"):
			logger.info("Using configState_getValues")
			config_states = configService.configState_getValues(
				config_ids=config_ids, object_ids=[self.get("global", "host_id")], with_defaults=True
			).get(self.get("global", "host_id"), {})
		else:
			logger.info("Using configState_getObjects")
			for config in configService.config_getObjects(id=config_ids):
				config_states[config.id] = config.defaultValues
			for config_state in configService.configState_getObjects(objectId=self.get("global", "host_id"), configId=config_ids):
				config_states[config_state.configId] = config_state.values

		for config_id, values in config_states.items():
			if not values or not values[0]:
				continue

			if config_id == "opsiclientd.depot_server.depot_id" and values:
				try:
					depotId = forceHostId(values[0])
					depotIds.append(depotId)
					logger.notice("Depot was set to '%s' from configState %s", depotId, config_id)
				except Exception as err:
					logger.error("Failed to set depot id from values %s in configState %s: %s", values, config_id, err)
			elif not masterOnly and (config_id == "clientconfig.depot.dynamic") and values:
				dynamicDepot = forceBool(values[0])

			elif config_id == "clientconfig.depot.protocol" and values and not forceDepotProtocol:
				depotProtocol = values[0]
				logger.info("Using depot protocol '%s' from config state '%s'", depotProtocol, config_id)

		if event and event.eventConfig.depotProtocol and not forceDepotProtocol:
			logger.info("Using depot protocol '%s' from event '%s'", event.eventConfig.depotProtocol, event.eventConfig.getName())
			depotProtocol = event.eventConfig.depotProtocol

		if depotProtocol not in ("webdav", "cifs"):
			logger.error("Invalid protocol %s specified, using cifs", depotProtocol)
			depotProtocol = "cifs"

		if dynamicDepot:
			if not depotIds:
				logger.info("Dynamic depot selection enabled")
			else:
				logger.info("Dynamic depot selection enabled, but depot is already selected")
		else:
			logger.info("Dynamic depot selection disabled")

		if not depotIds:
			clientToDepotservers = configService.configState_getClientToDepotserver(
				clientIds=[self.get("global", "host_id")], masterOnly=bool(not dynamicDepot), productIds=productIds
			)
			if not clientToDepotservers:
				raise RuntimeError("Failed to get depot config from service")

			depotIds = [clientToDepotservers[0]["depotId"]]
			if dynamicDepot:
				depotIds.extend(clientToDepotservers[0].get("alternativeDepotIds", []))

		logger.debug("Fetching depot servers %s from config service", depotIds)
		masterDepot = None
		alternativeDepots = []
		for depot in configService.host_getObjects(type="OpsiDepotserver", id=depotIds):
			logger.trace("Depot: %s", depot)
			if depot.id == depotIds[0]:
				masterDepot = depot
			else:
				alternativeDepots.append(depot)

		if not masterDepot:
			raise RuntimeError(f"Failed to get info for master depot '{depotIds[0]}'")

		logger.info("Master depot for products %s is %s", productIds, masterDepot.id)
		selectedDepot = masterDepot
		if dynamicDepot:
			if alternativeDepots:
				logger.info("Got alternative depots for products: %s", productIds)
				for index, depot in enumerate(alternativeDepots, start=1):
					logger.info("%d. alternative depot is %s", index, depot.id)

				try:
					clientConfig = {
						"clientId": self.get("global", "host_id"),
						"opsiHostKey": self.get("global", "opsi_host_key"),
						"ipAddress": None,
						"netmask": None,
						"defaultGateway": None,
					}
					try:
						gateways = netifaces.gateways()
						clientConfig["defaultGateway"], iface_name = gateways["default"][netifaces.AF_INET]
						addr = netifaces.ifaddresses(iface_name)[netifaces.AF_INET][0]
						clientConfig["netmask"] = addr["netmask"]
						clientConfig["ipAddress"] = addr["addr"]
						logger.info(
							"Using the following network config for depot selection algorithm: iface=%s addr=%s/%s gw=%s",
							iface_name,
							addr["addr"],
							addr["netmask"],
							gateways["default"],
						)
					except Exception as gwe:
						raise RuntimeError(f"Failed to get network interface with default gateway: {gwe}") from gwe

					logger.info("Passing client configuration to depot selection algorithm: %s", clientConfig)

					depotSelectionAlgorithm = configService.getDepotSelectionAlgorithm()
					logger.trace("depotSelectionAlgorithm:\n%s", depotSelectionAlgorithm)

					currentLocals = locals()
					exec(depotSelectionAlgorithm, None, currentLocals)
					selectDepot = currentLocals["selectDepot"]

					selectedDepot = selectDepot(clientConfig=clientConfig, masterDepot=masterDepot, alternativeDepots=alternativeDepots)
					if not selectedDepot:
						selectedDepot = masterDepot
				except Exception as err:
					logger.error("Failed to select depot: %s", err, exc_info=True)
			else:
				logger.info("No alternative depot for products: %s", productIds)

		return selectedDepot, depotProtocol

	def selectDepotserver(
		self,
		configService: JSONRPCBackend,
		mode: str = "mount",
		event: Event | None = None,
		productIds: list[str] | None = None,
		masterOnly: bool = False,
	) -> None:
		assert mode in ("mount", "sync")
		productIds = forceProductIdList(productIds or [])

		logger.notice("Selecting depot for products %s", productIds)
		logger.notice("MasterOnly --> '%s'", masterOnly)

		if event and event.eventConfig.useCachedProducts:
			cacheDepotDir = os.path.join(self.get("cache_service", "storage_dir"), "depot").replace("\\", "/").replace("//", "/")
			logger.notice("Using depot cache: %s", cacheDepotDir)
			self.set_temporary_depot_path(cacheDepotDir)
			if RUNNING_ON_WINDOWS:
				self.setTemporaryDepotDrive(cacheDepotDir.split(":")[0] + ":")
			else:
				self.setTemporaryDepotDrive(cacheDepotDir)
			self.set("depot_server", "url", "smb://localhost/noshare/" + ("/".join(cacheDepotDir.split("/")[1:])))
			return

		selectedDepot, depotProtocol = self.getDepot(configService=configService, event=event, productIds=productIds, masterOnly=masterOnly)
		if not selectedDepot:
			logger.error("Failed to get depot server")
			return

		logger.notice("Selected depot for mode '%s' is '%s', protocol '%s'", mode, selectedDepot, depotProtocol)
		self.set("depot_server", "depot_id", selectedDepot.id)
		if depotProtocol == "webdav":
			self.set("depot_server", "url", selectedDepot.depotWebdavUrl)
		else:
			self.set("depot_server", "url", selectedDepot.depotRemoteUrl)

	def getDepotserverCredentials(self, configService: JSONRPCBackend) -> tuple[str, str]:
		url = urlparse(self.get("depot_server", "url"))
		if url.scheme in ("webdav", "webdavs", "http", "https"):
			return (self.get("global", "host_id"), self.get("global", "opsi_host_key"))

		if not configService:
			raise RuntimeError("Not connected to config service")

		depotServerUsername = self.get("depot_server", "username")
		encryptedDepotServerPassword = configService.user_getCredentials(username="pcpatch", hostId=self.get("global", "host_id"))[
			"password"
		]
		depotServerPassword = blowfishDecrypt(self.get("global", "opsi_host_key"), encryptedDepotServerPassword)
		secret_filter.add_secrets(depotServerPassword)
		logger.debug("Using username '%s' for depot connection", depotServerUsername)
		return (depotServerUsername, depotServerPassword)

	def getFromService(self, service_client: ServiceClient | JSONRPCBackend) -> None:
		"""Get settings from service"""
		logger.notice("Getting config from service")
		if not service_client:
			raise RuntimeError("Config service is undefined")

		config_ids = [
			"clientconfig.configserver.url",
			"clientconfig.depot.drive",
			"clientconfig.depot.id",
			"clientconfig.depot.user",
			"clientconfig.suspend_bitlocker_on_reboot",
			"opsiclientd.*",  # everything starting with opsiclientd.
		]
		config_states = {}
		use_get_objects = True
		if hasattr(service_client, "configState_getValues"):
			use_get_objects = False
			logger.info("Using configState_getValues")
			config_states = service_client.configState_getValues(
				config_ids=config_ids, object_ids=[self.get("global", "host_id")], with_defaults=True
			).get(self.get("global", "host_id"), {})
			if (
				"clientconfig.configserver.url" not in config_states
				and isinstance(service_client, ServiceClient)
				and service_client.service_is_opsiclientd()
			):
				# Workaround getValues bug of older opsiclientd
				logger.warning("Service is opsiclientd with getValues bug")
				use_get_objects = True
		if use_get_objects:
			logger.info("Using configState_getObjects")
			for config in service_client.config_getObjects(id=config_ids):  # type: ignore[union-attr]
				config_states[config.id] = config.defaultValues
			for config_state in service_client.configState_getObjects(  # type: ignore[union-attr]
				objectId=self.get("global", "host_id"),
				configId=config_ids,
			):
				config_states[config_state.configId] = config_state.values

		self.setProductCachingMode(False)
		wan_vpn = False
		for config_id, values in config_states.items():
			logger.info("Got config state from service: %r=%r", config_id, values)

			if not values:
				logger.debug("No values - skipping %s", config_id)
				continue

			if config_id == "clientconfig.configserver.url":
				self.set("config_service", "url", values)
			elif config_id == "clientconfig.depot.drive":
				self.set("depot_server", "drive", values[0])
			elif config_id == "clientconfig.depot.id":
				self.set("depot_server", "depot_id", values[0])
			elif config_id == "clientconfig.depot.user":
				self.set("depot_server", "username", values[0])
			elif config_id == "clientconfig.suspend_bitlocker_on_reboot":
				self.set("global", "suspend_bitlocker_on_reboot", values[0])
			elif config_id == "clientconfig.wan_vpn":
				wan_vpn = values and values[0]

			elif config_id.startswith("opsiclientd."):
				try:
					parts = config_id.lower().split(".")
					if len(parts) < 3:
						logger.debug("Expected at least 3 parts in %s - skipping", config_id)
						continue

					value = values
					if len(value) == 1:
						value = value[0]
					self.set(section=parts[1], option=parts[2], value=value)
				except Exception as err:
					logger.error("Failed to process configState '%s': %s", config_id, err)

		if wan_vpn:
			logger.info("WAN/VPN mode enabled")
			self.setProductCachingMode(True)

		logger.notice("Got config from service")
		logger.debug("Config is now:\n %s", objectToBeautifiedText(self.getDict()))

	def setProductCachingMode(self, activated: bool) -> None:
		if activated:
			self.set("event_net_connection", "active", False)
			self.set("event_timer", "active", True)
			if RUNNING_ON_WINDOWS:
				self.set("event_gui_startup", "active", False)
				self.set("event_opsiclientd_start", "active", False)
				self.set("event_gui_startup{cache_ready}", "active", True)
				self.set("event_gui_startup{cache_ready}", "use_cached_config", False)
				self.set("event_gui_startup{cache_ready}", "use_cached_products", True)
			else:
				self.set("event_gui_startup", "active", False)
				self.set("event_opsiclientd_start", "active", False)
				self.set("event_opsiclientd_start{cache_ready}", "active", True)
				self.set("event_opsiclientd_start{cache_ready}", "use_cached_config", False)
				self.set("event_opsiclientd_start{cache_ready}", "use_cached_products", True)
			self.set("event_sync", "sync_config_from_server", False)
			self.set("event_sync", "sync_config_to_server", False)
			self.set("event_sync", "cache_products", True)
			self.set("precondition_cache_ready_user_logged_in", "config_cached", False)
			self.set("precondition_cache_ready_user_logged_in", "products_cached", True)
			self.set("precondition_cache_ready", "config_cached", False)
			self.set("precondition_cache_ready", "products_cached", True)
		else:
			self.set("event_net_connection", "active", False)
			self.set("event_timer", "active", True)
			if RUNNING_ON_WINDOWS:
				self.set("event_gui_startup", "active", True)
				self.set("event_opsiclientd_start", "active", False)
			else:
				self.set("event_gui_startup", "active", False)
				self.set("event_opsiclientd_start", "active", True)
			self.set("event_gui_startup{cache_ready}", "active", False)
			self.set("event_opsiclientd_start{cache_ready}", "active", False)
			self.set("event_gui_startup{cache_ready}", "use_cached_config", True)
			self.set("event_gui_startup{cache_ready}", "use_cached_products", True)
			self.set("event_opsiclientd_start{cache_ready}", "use_cached_config", True)
			self.set("event_opsiclientd_start{cache_ready}", "use_cached_products", True)
			self.set("event_sync", "sync_config_from_server", True)
			self.set("event_sync", "sync_config_to_server", True)
			self.set("event_sync", "cache_products", True)
			self.set("precondition_cache_ready_user_logged_in", "config_cached", True)
			self.set("precondition_cache_ready_user_logged_in", "products_cached", True)
			self.set("precondition_cache_ready", "config_cached", True)
			self.set("precondition_cache_ready", "products_cached", True)
