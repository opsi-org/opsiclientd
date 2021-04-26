# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0
"""
setup tasks
"""

import os
import codecs
import ipaddress
import subprocess

from OpenSSL.crypto import FILETYPE_PEM, load_certificate, load_privatekey
from OpenSSL.crypto import Error as CryptoError

from opsicommon.logging import logger, secret_filter
from opsicommon.ssl import as_pem, create_ca, create_server_cert, remove_ca
from opsicommon.system.network import get_ip_addresses, get_hostnames, get_fqdn
from opsicommon.client.jsonrpc import JSONRPCClient

from opsiclientd.Config import Config
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS, RUNNING_ON_LINUX, RUNNING_ON_MACOS

config = Config()

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

def setup_ssl():
	logger.info("Checking server cert")

	if not config.get('global', 'install_opsi_ca_into_os_store'):
		try:
			if remove_ca("opsi CA"):
				logger.info("opsi CA successfully removed from system cert store")
		except Exception as err:  # pylint: disable=broad-except
			logger.error("Failed to remove opsi CA from system cert store: %s", err)

	key_file = config.get('control_server', 'ssl_server_key_file')
	cert_file = config.get('control_server', 'ssl_server_cert_file')
	server_cn = get_fqdn()
	create = False

	if not os.path.exists(key_file) or not os.path.exists(cert_file):
		create = True
	else:
		try:
			with open(cert_file, "r") as file:
				srv_crt = load_certificate(FILETYPE_PEM, file.read())
				if server_cn != srv_crt.get_subject().CN:
					logger.notice(
						"Server CN has changed from '%s' to '%s', creating new server cert",
						srv_crt.get_subject().CN, server_cn
					)
					create = True
			with open(key_file, "r") as file:
				srv_key = load_privatekey(FILETYPE_PEM, file.read())
		except CryptoError as err:
			logger.error(err)
			create = True

	if create:
		logger.notice("Creating tls server certificate")
		# TODO: fetch from config service
		#pem = get_backend().host_getTLSCertificate(server_cn)  # pylint: disable=no-member
		#srv_crt = load_certificate(FILETYPE_PEM, pem)
		#srv_key = load_privatekey(FILETYPE_PEM, pem)

		(ca_cert, ca_key) = create_ca(
			subject={"commonName": get_fqdn()},
			valid_days=10000
		)
		(srv_cert, srv_key) = create_server_cert(
			subject={"commonName": get_fqdn()},
			valid_days=10000,
			ip_addresses=get_ips(),
			hostnames=get_hostnames(),
			ca_key=ca_key,
			ca_cert=ca_cert
		)

		# key_file and cert_file can be the same file
		if os.path.exists(key_file):
			os.unlink(key_file)
		if os.path.exists(cert_file):
			os.unlink(cert_file)

		if not os.path.exists(os.path.dirname(key_file)):
			os.makedirs(os.path.dirname(key_file))
		with open(key_file, "a") as out:
			out.write(as_pem(srv_key))

		if not os.path.exists(os.path.dirname(cert_file)):
			os.makedirs(os.path.dirname(cert_file))
		with open(cert_file, "a") as out:
			out.write(as_pem(srv_cert))

	logger.info("Server cert is up to date")
	return False


def setup_firewall_linux():
	logger.notice("Configure iptables")
	port = config.get('control_server', 'port')
	cmds = []
	if os.path.exists("/usr/bin/firewall-cmd"):
		# openSUSE Leap
		cmds.append(["/usr/bin/firewall-cmd", f"--add-port={port}/tcp", "--zone", "public"])
	else:
		for iptables in ("iptables", "ip6tables"):
			cmds.append([iptables, "-A", "INPUT", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"])

	for cmd in cmds:
		logger.info("Running command: %s", str(cmd))
		subprocess.call(cmd)


def setup_firewall_macos():
	logger.notice("Configure MacOS firewall")
	cmds = []

	for path in ("/usr/local/bin/opsiclientd", "/usr/local/lib/opsiclientd/opsiclientd"):
		cmds.append(["/usr/libexec/ApplicationFirewall/socketfilterfw", "--add" , path])
		cmds.append(["/usr/libexec/ApplicationFirewall/socketfilterfw", "--unblockapp" , path])

	for cmd in cmds:
		logger.info("Running command: %s", str(cmd))
		subprocess.call(cmd)


def setup_firewall():
	if RUNNING_ON_LINUX:
		return setup_firewall_linux()
	if RUNNING_ON_MACOS:
		return setup_firewall_macos()
	return None


def install_service_windows():
	logger.notice("Installing windows service")
	from opsiclientd.windows.service import handle_commandline # pylint: disable=import-outside-toplevel
	handle_commandline(argv=["opsiclientd.exe", "--startup", "auto", "install"])


def install_service_linux():
	logger.notice("Install systemd service")
	#subprocess.check_call(["systemctl", "daemon-reload"])
	subprocess.check_call(["systemctl", "enable", "opsiclientd.service"])


def install_service():
	if RUNNING_ON_WINDOWS:
		return install_service_windows()
	if RUNNING_ON_LINUX:
		return install_service_linux()
	#if RUNNING_ON_MACOS:
	#	install_service_macos()
	return None


def opsi_service_setup(options=None):
	try:
		config.readConfigFile()
	except Exception as err:  # pylint: disable=broad-except
		logger.info(err)

	service_address = getattr(options, "service_address", None) or config.get('config_service', 'url')[0]
	service_username = getattr(options, "service_username", None) or config.get('global', 'host_id')
	service_password = getattr(options, "service_password", None) or config.get('global', 'opsi_host_key')
	if getattr(options, "client_id", None):
		config.set('global', 'host_id', options.client_id)
	if not config.get('global', 'host_id'):
		fqdn = get_fqdn()
		fqdn = config.set('global', 'host_id', fqdn)

	secret_filter.add_secrets(service_password)

	logger.notice("Connecting to '%s' as '%s'", service_address, service_username)
	jsonrpc_client = JSONRPCClient(
		address=service_address,
		username=service_username,
		password=service_password
	)
	client = jsonrpc_client.host_getObjects(id=config.get('global', 'host_id'))  # pylint: disable=no-member
	if client and client[0] and client[0].opsiHostKey:
		config.set('global', 'opsi_host_key', client[0].opsiHostKey)

	config.getFromService(jsonrpc_client)
	config.updateConfigFile(force=True)


def setup_on_shutdown():
	if not RUNNING_ON_WINDOWS:
		return None

	# pyright: reportMissingImports=false
	import winreg  # pylint: disable=import-outside-toplevel,import-error
	import win32process  # pylint: disable=import-outside-toplevel,import-error

	GPO_NAME = "opsi shutdown install policy"
	BASE_KEYS = [
		r"SOFTWARE\Microsoft\Windows\CurrentVersion\Group Policy\State\Machine\Scripts\Shutdown",
		r"SOFTWARE\Microsoft\Windows\CurrentVersion\Group Policy\Scripts\Shutdown"
	]

	opsiclientd_rpc = os.path.realpath(config.get('opsiclientd_rpc', 'command').split('"')[1].strip('"'))
	if not opsiclientd_rpc:
		opsiclientd_rpc = os.path.join(os.path.dirname(os.path.realpath(__file__)), "opsiclientd_rpc.exe")

	# Windows does not execute binaries directly, using cmd script
	script_path = opsiclientd_rpc[:-3] + "cmd"
	with codecs.open(script_path, "w", "windows-1252") as file:
		file.write(f'"%~dp0\\{os.path.basename(opsiclientd_rpc)}" %*\r\n')
	script_params = "runOnShutdown()"

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

		key_handle = winreg.CreateKey(key_handle, "0")
		winreg.SetValueEx(key_handle, "Script", 0, winreg.REG_SZ, script_path)
		winreg.SetValueEx(key_handle, "Parameters", 0, winreg.REG_SZ, script_params)
		winreg.SetValueEx(key_handle, "ErrorCode", 0, winreg.REG_DWORD, 0)
		winreg.SetValueEx(key_handle, "IsPowershell", 0, winreg.REG_DWORD, 0)
		winreg.SetValueEx(key_handle, "ExecTime", 0, winreg.REG_BINARY, b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00")

	key_handle = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System")
	if win32process.IsWow64Process():
		winreg.DisableReflectionKey(key_handle)
	winreg.SetValueEx(key_handle, "MaxGPOScriptWait", 0, winreg.REG_DWORD, 0)
	#winreg.SetValueEx(key_handle, "ShutdownWithoutLogon", 0, winreg.REG_DWORD, 1)


def setup(full=False, options=None) -> None:
	logger.notice("Running opsiclientd setup")

	if full:
		opsi_service_setup(options)
		try:
			install_service()
		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to install service: %s", err)

	try:
		setup_ssl()
	except Exception as err: # pylint: disable=broad-except
		logger.error("Failed to setup ssl: %s", err, exc_info=True)

	try:
		setup_firewall()
	except Exception as err:  # pylint: disable=broad-except
		logger.error("Failed to setup firewall: %s", err, exc_info=True)

	try:
		setup_on_shutdown()
	except Exception as err:  # pylint: disable=broad-except
		logger.error("Failed to setup on_shutdown: %s", err, exc_info=True)
