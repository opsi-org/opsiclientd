# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0
"""
setup tasks
"""

import os
import ipaddress
import subprocess

from OpenSSL.crypto import FILETYPE_PEM, load_certificate, load_privatekey
from OpenSSL.crypto import Error as CryptoError

from opsicommon.logging import logger, secret_filter
from opsicommon.ssl import as_pem, create_ca, create_server_cert, remove_ca
from opsicommon.system.network import get_ip_addresses, get_hostnames, get_fqdn
from opsicommon.client.jsonrpc import JSONRPCClient

from opsiclientd import get_opsiclientd_pid
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
	handle_commandline(argv=["opsiclientd.exe", "install"])

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

def setup(full=False, options=None) -> None:
	logger.notice("Running opsiclientd setup")

	if full:
		opsiclientd_pid = get_opsiclientd_pid()
		if opsiclientd_pid:
			logger.info("opsiclientd is running with pid %d", opsiclientd_pid)
		else:
			logger.info("opsiclientd is not running")

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

		"""
		else:
			logger.notice("Creating client '%s' in service", config.get('global', 'host_id'))
			jsonrpc_client.host_createOpsiClient(  # pylint: disable=no-member
				id=config.get('global', 'host_id')
			)
			client = jsonrpc_client.host_getObjects(id=config.get('global', 'host_id'))  # pylint: disable=no-member
			if not client:
				raise RuntimeError(f"Client '{config.get('global', 'host_id')}' not found in service")
		"""
		config.getFromService(jsonrpc_client)
		config.updateConfigFile(force=True)

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
