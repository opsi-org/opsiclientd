# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
setup tasks
"""

import codecs
import datetime
import ipaddress
import os
import subprocess
from argparse import Namespace
from pathlib import Path

from OpenSSL.crypto import FILETYPE_PEM  # type: ignore[import]
from OpenSSL.crypto import Error as CryptoError
from OpenSSL.crypto import load_certificate, load_privatekey  # type: ignore[import]
from opsicommon.client.opsiservice import ServiceClient  # type: ignore[import]
from opsicommon.logging import logger, secret_filter  # type: ignore[import]
from opsicommon.ssl import as_pem, create_ca, create_server_cert  # type: ignore[import]
from opsicommon.system.network import (  # type: ignore[import]
	get_fqdn,
	get_hostnames,
	get_ip_addresses,
)

from opsiclientd import __version__
from opsiclientd.Config import Config
from opsiclientd.OpsiService import update_ca_cert
from opsiclientd.SystemCheck import (
	RUNNING_ON_LINUX,
	RUNNING_ON_MACOS,
	RUNNING_ON_WINDOWS,
)

if not RUNNING_ON_WINDOWS:
	WindowsError = RuntimeError

config = Config()

CERT_RENEW_DAYS = 60


def get_ips():
	ips = {"127.0.0.1", "::1"}
	for addr in get_ip_addresses():
		if addr["family"] in ("ipv4", "ipv6") and addr["address"] not in ips:
			if addr["address"].startswith("fe80"):
				continue
			try:
				ips.add(ipaddress.ip_address(addr["address"]).compressed)
			except ValueError as err:
				logger.warning(err)
	return ips


def get_service_client(address: str | None = None, username: str | None = None, password: str | None = None) -> ServiceClient:
	return ServiceClient(
		address=address or config.get("config_service", "url")[0],
		username=username or config.get("global", "host_id"),
		password=password or config.get("global", "opsi_host_key"),
		ca_cert_file=config.ca_cert_file,
		verify=config.service_verification_flags,
		proxy_url=config.get("global", "proxy_url"),
		user_agent=f"opsiclientd/{__version__}",
		connect_timeout=config.get("config_service", "connection_timeout"),
		jsonrpc_create_objects=True,
	)


def setup_ssl(full: bool = False):  # pylint: disable=too-many-branches,too-many-statements,too-many-locals
	logger.info("Checking server cert")

	key_file = config.get("control_server", "ssl_server_key_file")
	cert_file = config.get("control_server", "ssl_server_cert_file")
	server_cn = config.get("global", "host_id")
	if not server_cn:
		server_cn = get_fqdn()
	create = False
	exists_self_signed = False
	if not os.path.exists(key_file) or not os.path.exists(cert_file):
		create = True
	else:
		try:
			with open(cert_file, "r", encoding="utf-8") as file:
				srv_crt = load_certificate(FILETYPE_PEM, file.read())
				enddate = datetime.datetime.strptime(srv_crt.get_notAfter().decode("utf-8"), "%Y%m%d%H%M%SZ")
				diff = (enddate - datetime.datetime.now()).days

				logger.info("Server cert '%s' will expire in %d days", srv_crt.get_subject().CN, diff)
				if diff <= CERT_RENEW_DAYS:
					logger.notice("Server cert '%s' will expire in %d days, needing new cert", srv_crt.get_subject().CN, diff)
					create = True
				elif server_cn != srv_crt.get_subject().CN:
					logger.notice("Server CN has changed from '%s' to '%s', needing new cert", srv_crt.get_subject().CN, server_cn)
					create = True
				elif full and srv_crt.get_issuer().CN == srv_crt.get_subject().CN:
					logger.notice("Self signed certificate found, needing new cert")
					create = True
					exists_self_signed = True

			if not create:
				with open(key_file, "r", encoding="utf-8") as file:
					srv_key = load_privatekey(FILETYPE_PEM, file.read())
		except CryptoError as err:
			logger.error(err)
			create = True

	if not create:
		logger.info("Server cert is up to date")
		return

	(srv_crt, srv_key) = (None, None)
	try:
		logger.notice("Fetching tls server certificate from config service")
		config.readConfigFile()

		service_client = get_service_client()
		try:
			pem = service_client.jsonrpc(method="host_getTLSCertificate", params=[server_cn])  # pylint: disable=no-member
			srv_crt = load_certificate(FILETYPE_PEM, pem)
			srv_key = load_privatekey(FILETYPE_PEM, pem)
		finally:
			service_client.disconnect()
	except Exception as err:  # pylint: disable=broad-except
		logger.warning("Failed to fetch tls certificate from server: %s", err)
		if exists_self_signed:
			return

	if not srv_crt or not srv_key:
		logger.notice("Creating self-signed tls server certificate")
		(ca_cert, ca_key) = create_ca(subject={"commonName": server_cn}, valid_days=10000)
		(srv_crt, srv_key) = create_server_cert(
			subject={"commonName": server_cn},
			valid_days=10000,
			ip_addresses=get_ips(),
			hostnames=get_hostnames(),
			ca_key=ca_key,
			ca_cert=ca_cert,
		)

	# key_file and cert_file can be the same file
	if os.path.exists(key_file):
		os.unlink(key_file)
	if os.path.exists(cert_file):
		os.unlink(cert_file)

	if not os.path.exists(os.path.dirname(key_file)):
		os.makedirs(os.path.dirname(key_file))
	with open(key_file, "a", encoding="utf-8") as out:
		out.write(as_pem(srv_key))

	if not os.path.exists(os.path.dirname(cert_file)):
		os.makedirs(os.path.dirname(cert_file))
	with open(cert_file, "a", encoding="utf-8") as out:
		out.write(as_pem(srv_crt))


def setup_firewall_linux():
	logger.notice("Configure firewall")
	port = config.get("control_server", "port")
	cmds = []
	if os.path.exists("/usr/bin/firewall-cmd"):
		# openSUSE Leap
		cmds.append(["/usr/bin/firewall-cmd", f"--add-port={port}/tcp", "--zone", "public"])
	elif os.path.exists("/sbin/SuSEfirewall2"):
		# other SUSE
		cmds.append(["/sbin/SuSEfirewall2", "open", "EXT", "TCP" f"{port}"])
	elif os.path.exists("/usr/sbin/ucr"):
		# UCS
		cmds.append(["/usr/sbin/ucr", "set", f"security/packetfilter/package/opsiclientd/tcp/{port}/all=ACCEPT"])
		cmds.append(["/usr/sbin/service", "univention-firewall", "restart"])
	elif os.path.exists("/sbin/iptables"):
		for iptables in ("iptables", "ip6tables"):
			cmds.append([iptables, "-A", "INPUT", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"])
	else:
		logger.warning("Could not configure firewall - no suitable executable found.")

	for cmd in cmds:
		logger.info("Running command: %s", str(cmd))
		subprocess.call(cmd)


def setup_firewall_macos():
	logger.notice("Configure MacOS firewall")
	cmds = []

	for path in ("/usr/local/bin/opsiclientd", "/usr/local/lib/opsiclientd/opsiclientd"):
		cmds.append(["/usr/libexec/ApplicationFirewall/socketfilterfw", "--add", path])
		cmds.append(["/usr/libexec/ApplicationFirewall/socketfilterfw", "--unblockapp", path])

	for cmd in cmds:
		logger.info("Running command: %s", str(cmd))
		subprocess.call(cmd)


def setup_firewall_windows():
	logger.notice("Configure Windows firewall")
	port = config.get("control_server", "port")
	cmds = [["netsh", "advfirewall", "firewall", "delete", "rule", 'name="opsiclientd-control-port"']]
	cmds.append(
		[
			"netsh",
			"advfirewall",
			"firewall",
			"add",
			"rule",
			'name="opsiclientd-control-port"',
			"dir=in",
			"action=allow",
			"protocol=TCP",
			f"localport={port}",
		]
	)

	for cmd in cmds:
		logger.info("Running command: %s", str(cmd))
		subprocess.call(cmd)


def setup_firewall():
	if RUNNING_ON_LINUX:
		return setup_firewall_linux()
	if RUNNING_ON_MACOS:
		return setup_firewall_macos()
	if RUNNING_ON_WINDOWS:
		return setup_firewall_windows()
	return None


def install_service_windows():
	logger.notice("Installing windows service")
	from opsiclientd.windows.service import (  # pylint: disable=import-outside-toplevel
		handle_commandline,
	)

	handle_commandline(argv=["opsiclientd.exe", "--startup", "auto", "install"])

	# pyright: reportMissingImports=false
	import winreg  # pylint: disable=import-outside-toplevel,import-error

	import win32process  # type: ignore[import] # pylint: disable=import-outside-toplevel,import-error

	key_handle = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\opsiclientd")
	if win32process.IsWow64Process():
		winreg.DisableReflectionKey(key_handle)
	winreg.SetValueEx(key_handle, "DependOnService", 0, winreg.REG_MULTI_SZ, ["Dhcp"])
	# winreg.SetValueEx(key_handle, 'DependOnService', 0, winreg.REG_MULTI_SZ, ["Dhcp", "Dnscache"])
	winreg.CloseKey(key_handle)

	key_handle = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control")
	if win32process.IsWow64Process():
		winreg.DisableReflectionKey(key_handle)
	winreg.SetValueEx(key_handle, "ServicesPipeTimeout", 0, winreg.REG_DWORD, 120000)
	winreg.CloseKey(key_handle)


def install_service_linux():
	logger.notice("Install systemd service")
	# subprocess.check_call(["systemctl", "daemon-reload"])
	subprocess.check_call(["systemctl", "enable", "opsiclientd.service"])


def install_service_macos():
	logger.notice("Bootstrap launchd service")
	subprocess.check_call(["launchctl", "bootstrap", "system", "/Library/LaunchDaemons/org.opsi.opsiclientd.plist"])


def install_service():
	if RUNNING_ON_WINDOWS:
		return install_service_windows()
	if RUNNING_ON_LINUX:
		return install_service_linux()
	if RUNNING_ON_MACOS:
		return install_service_macos()
	return None


def opsi_service_setup(options=None):
	try:
		config.readConfigFile()
	except Exception as err:  # pylint: disable=broad-except
		logger.info(err)

	if os.path.exists(config.ca_cert_file):
		# Delete ca cert which could be invalid or expired
		os.remove(config.ca_cert_file)

	service_address = getattr(options, "service_address", None) or config.get("config_service", "url")[0]
	service_username = getattr(options, "service_username", None) or config.get("global", "host_id")
	service_password = getattr(options, "service_password", None) or config.get("global", "opsi_host_key")
	if getattr(options, "client_id", None):
		config.set("global", "host_id", options.client_id)
	if not config.get("global", "host_id"):
		fqdn = get_fqdn()
		fqdn = config.set("global", "host_id", fqdn)

	secret_filter.add_secrets(service_password)

	logger.notice("Connecting to '%s' as '%s'", service_address, service_username)
	service_client = get_service_client(address=service_address, username=service_username, password=service_password)

	try:
		update_ca_cert(service_client, allow_remove=False)
	except Exception as err:  # pylint: disable=broad-except
		logger.error(err, exc_info=True)

	try:
		client = service_client.jsonrpc(method="host_getObjects", params=[[], {"id": config.get("global", "host_id")}])
		if client and client[0] and client[0].opsiHostKey:
			config.set("global", "opsi_host_key", client[0].opsiHostKey)

		config.getFromService(service_client)
		config.updateConfigFile(force=True)
	finally:
		service_client.disconnect()


def cleanup_registry_uninstall():
	if not RUNNING_ON_WINDOWS:
		return None

	logger.notice("Cleanup registry uninstall information")
	# pyright: reportMissingImports=false
	import winreg  # pylint: disable=import-outside-toplevel,import-error

	modified = True
	while modified:
		modified = False
		# We need to start over iterating after key change
		with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall") as key:
			for idx in range(1024):
				try:
					uninstall_key = winreg.EnumKey(key, idx)
					logger.debug("Processing key %r", uninstall_key)
				except WindowsError as err:
					if err.errno == 22:  # type: ignore[attr-defined] # pylint: disable=no-member
						logger.debug("No more subkeys")
						break
					logger.debug(err)

				if uninstall_key == "opsi-client-agent":
					# Keep this entry
					continue

				display_name = None
				with winreg.OpenKey(key, uninstall_key) as subkey:
					try:
						display_name = winreg.QueryValueEx(subkey, "DisplayName")[0]
					except FileNotFoundError:
						pass

				if display_name and display_name.startswith("opsi-client-agent"):
					logger.info("Removing uninstall key %r (DisplayName=%r)", uninstall_key, display_name)
					winreg.DeleteKey(key, uninstall_key)
					modified = True
					# Restart iteration
					break


def setup_on_shutdown():  # pylint: disable=too-many-statements
	if not RUNNING_ON_WINDOWS:
		return None

	logger.notice("Creating opsi shutdown install policy")
	# pyright: reportMissingImports=false
	import winreg  # pylint: disable=import-outside-toplevel,import-error

	import win32process  # pylint: disable=import-outside-toplevel,import-error

	GPO_NAME = "opsi shutdown install policy"
	BASE_KEYS = [
		r"SOFTWARE\Microsoft\Windows\CurrentVersion\Group Policy\State\Machine\Scripts\Shutdown",
		r"SOFTWARE\Microsoft\Windows\CurrentVersion\Group Policy\Scripts\Shutdown",
	]

	opsiclientd_rpc = None
	try:
		opsiclientd_rpc = os.path.realpath(config.get("opsiclientd_rpc", "command").split('"')[1].strip('"'))
	except IndexError:
		pass
	if not opsiclientd_rpc:
		opsiclientd_rpc = os.path.join(os.path.dirname(os.path.realpath(__file__)), "opsiclientd_rpc.exe")

	# Windows does not execute binaries directly, using cmd script
	script_path = opsiclientd_rpc[:-3] + "cmd"
	with codecs.open(script_path, "w", "windows-1252") as file:
		file.write(f'"%~dp0\\{os.path.basename(opsiclientd_rpc)}" %*\r\n')
	script_params = "--timeout=18000 runOnShutdown()"

	for base_key in BASE_KEYS:
		base_key_handle = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, base_key)
		if win32process.IsWow64Process():
			winreg.DisableReflectionKey(base_key_handle)

		num = -1
		while True:
			num += 1
			try:
				key_handle = winreg.OpenKey(base_key_handle, str(num))
				(value, _type) = winreg.QueryValueEx(key_handle, "GPOName")
				winreg.CloseKey(key_handle)
				if value == GPO_NAME:
					break
			except OSError:
				# Key does not exist
				break

		key_handle = winreg.CreateKey(base_key_handle, str(num))
		winreg.SetValueEx(key_handle, "GPO-ID", 0, winreg.REG_SZ, "LocalGPO")
		winreg.SetValueEx(key_handle, "SOM-ID", 0, winreg.REG_SZ, "Local")
		winreg.SetValueEx(key_handle, "FileSysPath", 0, winreg.REG_SZ, rf"{os.environ['SystemRoot']}\System32\GroupPolicy\Machine")
		winreg.SetValueEx(key_handle, "DisplayName", 0, winreg.REG_SZ, GPO_NAME)
		winreg.SetValueEx(key_handle, "GPOName", 0, winreg.REG_SZ, GPO_NAME)
		winreg.SetValueEx(key_handle, "PSScriptOrder", 0, winreg.REG_DWORD, 1)

		key_handle2 = winreg.CreateKey(key_handle, "0")
		winreg.SetValueEx(key_handle2, "Script", 0, winreg.REG_SZ, script_path)
		winreg.SetValueEx(key_handle2, "Parameters", 0, winreg.REG_SZ, script_params)
		winreg.SetValueEx(key_handle2, "ErrorCode", 0, winreg.REG_DWORD, 0)
		winreg.SetValueEx(key_handle2, "IsPowershell", 0, winreg.REG_DWORD, 0)
		winreg.SetValueEx(
			key_handle2, "ExecTime", 0, winreg.REG_BINARY, b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
		)

		winreg.CloseKey(key_handle2)
		winreg.CloseKey(key_handle)
		winreg.CloseKey(base_key_handle)

	key_handle = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System")
	if win32process.IsWow64Process():
		winreg.DisableReflectionKey(key_handle)
	winreg.SetValueEx(key_handle, "MaxGPOScriptWait", 0, winreg.REG_DWORD, 0)
	# winreg.SetValueEx(key_handle, "ShutdownWithoutLogon", 0, winreg.REG_DWORD, 1)
	winreg.CloseKey(key_handle)


def cleanup_control_server_files():
	share_dir = Path(config.get("control_server", "files_dir"))
	if not share_dir.exists():
		logger.info("Creating files directory %s", share_dir)
		share_dir.mkdir(parents=True)
	for content in share_dir.iterdir():
		if content.is_file():
			logger.debug("Deleting file %s", content)
			content.unlink()


def setup(full: bool = False, options: Namespace = None) -> None:
	logger.notice("Running opsiclientd setup")
	errors = []

	if full:
		opsi_service_setup(options)
		try:
			install_service()
		except Exception as err:  # pylint: disable=broad-except
			logger.error("Failed to install service: %s", err, exc_info=True)
			errors.append(str(err))

	try:
		setup_ssl(full)
	except Exception as err:  # pylint: disable=broad-except
		logger.error("Failed to setup ssl: %s", err, exc_info=True)
		errors.append(str(err))

	try:
		cleanup_registry_uninstall()
	except Exception as err:  # pylint: disable=broad-except
		logger.error("Failed to clean cleanup_registry_uninstall: %s", err, exc_info=True)
		errors.append(str(err))

	if not config.get("control_server", "skip_setup_firewall"):
		try:
			setup_firewall()
		except Exception as err:  # pylint: disable=broad-except
			logger.error("Failed to setup firewall: %s", err, exc_info=True)
			errors.append(str(err))

	try:
		setup_on_shutdown()
	except Exception as err:  # pylint: disable=broad-except
		logger.error("Failed to setup on_shutdown: %s", err, exc_info=True)
		errors.append(str(err))

	try:
		cleanup_control_server_files()
	except Exception as err:  # pylint: disable=broad-except
		logger.error("Failed to clean control_server_files: %s", err, exc_info=True)

	logger.notice("Setup completed with %d errors", len(errors))
	if errors and full:
		raise RuntimeError(", ".join(errors))
