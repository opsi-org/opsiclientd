# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2025 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
setup tasks
"""

import datetime
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.x509.oid import NameOID
from opsicommon.client.opsiservice import ServiceClient
from opsicommon.logging import get_logger, secret_filter
from opsicommon.ssl import as_pem, create_ca, create_server_cert
from opsicommon.system import get_system_uuid
from opsicommon.system.network import get_fqdn, get_hostnames, get_network_info
from packaging import version

from opsiclientd import __version__
from opsiclientd.Config import Config
from opsiclientd.OpsiService import update_os_ca_store
from opsiclientd.SystemCheck import (
	RUNNING_ON_LINUX,
	RUNNING_ON_MACOS,
	RUNNING_ON_WINDOWS,
)

if not RUNNING_ON_WINDOWS:
	WindowsError = RuntimeError

config = Config()
logger = get_logger()

CERT_RENEW_DAYS = 60
SERVICES_PIPE_TIMEOUT_WINDOWS = 120000


def get_ips() -> set[str]:
	ips = {"127.0.0.1", "::1"}
	for interface in get_network_info().interfaces:
		if interface.address.compressed not in ips:
			if interface.address.is_link_local:
				continue
			try:
				ips.add(interface.address.compressed)
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
		jsonrpc_create_methods=True,
	)


def setup_ssl(full: bool = False) -> None:
	logger.info("Checking server cert")

	key_file = config.get("control_server", "ssl_server_key_file")
	cert_file = config.get("control_server", "ssl_server_cert_file")
	server_cn = config.get("global", "host_id")
	if not server_cn:
		server_cn = get_fqdn()
	create = False
	exists_self_signed = False
	srv_crt: x509.Certificate | None = None
	srv_key: RSAPrivateKey | None = None
	if not os.path.exists(key_file) or not os.path.exists(cert_file):
		create = True
	else:
		try:
			with open(cert_file, "rb") as file:
				srv_crt = x509.load_pem_x509_certificate(file.read())
				enddate = srv_crt.not_valid_after_utc.replace(tzinfo=None)
				diff = (enddate - datetime.datetime.now()).days
				cert_server_cn = srv_crt.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[-1].value
				logger.info("Server cert '%s' will expire in %d days", server_cn, diff)
				if diff <= CERT_RENEW_DAYS:
					logger.notice("Server cert '%s' will expire in %d days, needing new cert", server_cn, diff)
					create = True
				elif cert_server_cn != server_cn:
					logger.notice("Server CN has changed from '%s' to '%s', needing new cert", cert_server_cn, server_cn)
					create = True
				elif full and srv_crt.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)[-1].value == cert_server_cn:
					logger.notice("Self signed certificate found, needing new cert")
					create = True
					exists_self_signed = True

			if not create:
				with open(key_file, "rb") as file:
					loaded_key = load_pem_private_key(file.read(), password=None)
					logger.info("Server key type: %s, %d bits", loaded_key.__class__.__name__, getattr(loaded_key, "key_size", 0))
					if not isinstance(loaded_key, RSAPrivateKey):
						raise ValueError(f"Invalid key type: {loaded_key.__class__.__name__}, needing new cert")
					if loaded_key.key_size < 2048:
						raise ValueError(f"Server key is only {loaded_key.key_size} bits long, needing new cert")
					srv_key = loaded_key
		except Exception as err:
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
		service_client.connect()
		try:
			pem = service_client.host_getTLSCertificate(server_cn)  # type: ignore[attr-defined]
			srv_crt = x509.load_pem_x509_certificate(pem.encode("utf-8"))
			loaded_key = load_pem_private_key(pem.encode("utf-8"), password=None)
			if isinstance(loaded_key, RSAPrivateKey):
				srv_key = loaded_key
			else:
				logger.error("Invalid key type: %r Recreating key", type(loaded_key))
		finally:
			service_client.disconnect()
	except Exception as err:
		logger.warning("Failed to fetch tls certificate from server: %s", err)
		if exists_self_signed:
			return

	if not srv_crt or not srv_key:
		logger.notice("Creating self-signed tls server certificate")
		(ca_cert, ca_key) = create_ca(subject={"commonName": server_cn}, valid_days=365)
		(srv_crt, srv_key) = create_server_cert(
			subject={"commonName": server_cn},
			valid_days=365,
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


def setup_firewall_linux() -> None:
	logger.notice("Configure firewall")
	port = config.get("control_server", "port")
	cmds = []
	if os.path.exists("/usr/bin/firewall-cmd"):
		# openSUSE Leap
		cmds.append(["/usr/bin/firewall-cmd", f"--add-port={port}/tcp", "--zone", "public"])
	elif os.path.exists("/sbin/SuSEfirewall2"):
		# other SUSE
		cmds.append(["/sbin/SuSEfirewall2", "open", "EXT", "TCP", f"{port}"])
	elif os.path.exists("/usr/sbin/ucr"):
		# UCS
		cmds.append(["/usr/sbin/ucr", "set", f"security/packetfilter/package/opsiclientd/tcp/{port}/all=ACCEPT"])
		cmds.append(["/usr/sbin/service", "univention-firewall", "restart"])
	elif os.path.exists("/sbin/iptables"):
		for iptables in ("iptables", "ip6tables"):
			cmds.append([iptables, "-A", "INPUT", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"])
	else:
		logger.warning("Could not configure firewall - no suitable executable found")

	for cmd in cmds:
		logger.info("Running command: %s", str(cmd))
		subprocess.call(cmd)


def setup_firewall_macos() -> None:
	logger.notice("Configure MacOS firewall")
	path = "/usr/local/lib/opsiclientd/opsiclientd"
	for cmd in (
		# --add will add the app multiple times, so remove first
		["/usr/libexec/ApplicationFirewall/socketfilterfw", "--remove", path],
		["/usr/libexec/ApplicationFirewall/socketfilterfw", "--add", path],
		["/usr/libexec/ApplicationFirewall/socketfilterfw", "--unblockapp", path],
	):
		logger.info("Running command: %s", str(cmd))
		subprocess.call(cmd)


def setup_firewall_windows() -> None:
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


def setup_firewall() -> None:
	if RUNNING_ON_LINUX:
		return setup_firewall_linux()
	if RUNNING_ON_MACOS:
		return setup_firewall_macos()
	if RUNNING_ON_WINDOWS:
		return setup_firewall_windows()
	return None


def install_service_windows() -> None:
	if sys.platform != "win32":
		return

	logger.notice("Installing windows service")
	from opsiclientd.windows.service import handle_commandline

	handle_commandline(argv=["opsiclientd.exe", "--startup", "auto", "install"])

	import winreg

	with winreg.CreateKeyEx(
		winreg.HKEY_LOCAL_MACHINE,
		r"SYSTEM\CurrentControlSet\Services\opsiclientd",
		0,
		winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY,
	) as key_handle:
		winreg.SetValueEx(key_handle, "DependOnService", 0, winreg.REG_MULTI_SZ, ["Dhcp"])
		# SC failure opsiclientd actions= restart/60000/restart/60000/restart/60000 reset= 86400
		failure_actions = "80510100000000000000000003000000140000000100000060ea00000100000060ea00000100000060ea0000"
		winreg.SetValueEx(key_handle, "FailureActions", 0, winreg.REG_BINARY, bytes.fromhex(failure_actions))

	with winreg.CreateKeyEx(
		winreg.HKEY_LOCAL_MACHINE,
		r"SYSTEM\CurrentControlSet\Control",
		0,
		winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY,
	) as key_handle:
		current_timeout = 0
		try:
			current_timeout = winreg.QueryValueEx(key_handle, "ServicesPipeTimeout", 0)[0]
		except Exception:
			logger.debug("Did not get ServicesPipeTimeout from registry")
		# Make sure to have a timeout of at least SERVICES_PIPE_TIMEOUT_WINDOWS
		if current_timeout < SERVICES_PIPE_TIMEOUT_WINDOWS:
			winreg.SetValueEx(key_handle, "ServicesPipeTimeout", 0, winreg.REG_DWORD, SERVICES_PIPE_TIMEOUT_WINDOWS)


def install_service_linux() -> None:
	logger.notice("Install opsiclientd service")
	# subprocess.check_call(["systemctl", "daemon-reload"])
	subprocess.check_call(["systemctl", "enable", "opsiclientd.service"])


def install_service_macos() -> None:
	logger.notice("Install opsiclientd service")
	proc = subprocess.run(["launchctl", "list"], check=False, capture_output=True, text=True)
	if "org.opsi.opsiclientd" in proc.stdout:  # on arm machines trying to bootstraps a present service leads to IO-Errors
		logger.info("opsiclientd service already installed")
		return

	proc = subprocess.run(
		["launchctl", "bootstrap", "system", "/Library/LaunchDaemons/org.opsi.opsiclientd.plist"],
		check=False,
		capture_output=True,
		text=True,
	)
	logger.debug("launchctl bootstrap output: %s", proc.stderr or "" + proc.stdout or "")
	if proc.returncode not in (0, 37):
		# 37 is the error code for "already bootstrapped"
		error = f"Failed to launchctl bootstrap opsiclientd service: {proc.returncode} - {proc.stderr or '' + proc.stdout or ''}"
		logger.error(error)
		raise RuntimeError(error)


def install_service() -> None:
	if RUNNING_ON_WINDOWS:
		return install_service_windows()
	if RUNNING_ON_LINUX:
		return install_service_linux()
	if RUNNING_ON_MACOS:
		return install_service_macos()
	return None


def opsi_service_setup(options: Namespace) -> None:
	try:
		config.readConfigFile()
	except Exception as err:
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
		config.set("global", "host_id", fqdn)

	secret_filter.add_secrets(service_password)

	logger.notice("Connecting to '%s' as '%s'", service_address, service_username)
	service_client = get_service_client(address=service_address, username=service_username, password=service_password)
	service_client.connect()

	try:
		update_os_ca_store(allow_remove=False)
	except Exception as err:
		logger.error(err, exc_info=True)

	try:
		clients = service_client.host_getObjects(id=config.get("global", "host_id"))  # type: ignore[attr-defined]
		if clients and clients[0] and clients[0].opsiHostKey:
			config.set("global", "opsi_host_key", clients[0].opsiHostKey)
			try:
				logger.debug("Connected to opsi server version %r", service_client.server_version)
				if service_client.server_version >= version.parse("4.3"):
					logger.debug("Connected to opsi server >= 4.3")
					system_uuid = get_system_uuid()
					logger.debug("system_uuid: %s", system_uuid)
					if system_uuid:
						logger.info("Updating systemUUID to %r", system_uuid)
						clients[0].systemUUID = system_uuid
						service_client.host_updateObjects(clients)  # type: ignore[attr-defined]
			except Exception as err:
				logger.error("Failed to update systemUUID: %s", err, exc_info=True)

		config.getFromService(service_client)
		config.updateConfigFile(force=True)
	finally:
		service_client.disconnect()


def cleanup_registry_uninstall() -> None:
	if sys.platform != "win32":
		return

	logger.notice("Cleanup registry uninstall information")
	import winreg

	modified = True
	while modified:
		modified = False
		# We need to start over iterating after key change
		with winreg.OpenKeyEx(
			winreg.HKEY_LOCAL_MACHINE,
			r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
			0,
			winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY,
		) as key:
			for idx in range(1024):
				try:
					uninstall_key = winreg.EnumKey(key, idx)
					logger.debug("Processing key %r", uninstall_key)
				except WindowsError as err:
					if err.errno == 22:  # type: ignore[attr-defined]
						logger.debug("No more subkeys")
						break
					logger.debug(err)

				if uninstall_key == "opsi-client-agent":
					# Keep this entry
					continue

				display_name = None
				with winreg.OpenKeyEx(key, uninstall_key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as subkey:
					try:
						display_name = winreg.QueryValueEx(subkey, "DisplayName")[0]
					except FileNotFoundError:
						pass

				if display_name and display_name.startswith("opsi-client-agent"):
					logger.info("Removing uninstall key %r (DisplayName=%r)", uninstall_key, display_name)
					winreg.DeleteKeyEx(key, uninstall_key, winreg.KEY_WOW64_64KEY)
					modified = True
					# Restart iteration
					break


def cleanup_registry_environment_path() -> None:
	if sys.platform != "win32":
		return

	logger.notice("Cleanup registry environment PATH variable")
	import winreg

	with winreg.CreateKeyEx(
		winreg.HKEY_LOCAL_MACHINE,
		r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
		0,
		winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY,
	) as key_handle:
		try:
			reg_value, value_type = winreg.QueryValueEx(key_handle, "PATH")
			logger.debug("Current PATH value (%r): %r", value_type, reg_value)
			cur_reg_values = reg_value.split(";")
			# Remove empty values and values containing "pywin32_system32" and "opsi"
			reg_values = list(dict.fromkeys(v for v in cur_reg_values if v and not ("pywin32_system32" in v and "opsi" in v)))
			if reg_values == cur_reg_values:
				logger.debug("PATH value unchanged")
				return

			reg_value = ";".join(reg_values)
			logger.debug("Setting new PATH value (%r): %r", value_type, reg_values)
			winreg.SetValueEx(key_handle, "PATH", 0, value_type, reg_value)
		except FileNotFoundError:
			logger.warning("Key 'PATH' not found in registry")


def setup_on_shutdown() -> None:
	if sys.platform != "win32":
		return None

	logger.notice("Creating opsi shutdown install policy")
	import winreg

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
	with open(script_path, "w", encoding="windows-1252") as file:
		file.write(f'"%~dp0\\{os.path.basename(opsiclientd_rpc)}" %*\r\n')
	script_params = "--timeout=18000 runOnShutdown()"

	for base_key in BASE_KEYS:
		with winreg.CreateKeyEx(
			winreg.HKEY_LOCAL_MACHINE, base_key, 0, winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
		) as base_key_handle:
			num = -1
			while True:
				num += 1
				try:
					with winreg.OpenKeyEx(base_key_handle, str(num), 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key_handle:
						(value, _type) = winreg.QueryValueEx(key_handle, "GPOName")
					if value == GPO_NAME:
						break
				except OSError:
					# Key does not exist
					break

			with winreg.CreateKeyEx(
				base_key_handle, str(num), 0, winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
			) as key_handle:
				winreg.SetValueEx(key_handle, "GPO-ID", 0, winreg.REG_SZ, "LocalGPO")
				winreg.SetValueEx(key_handle, "SOM-ID", 0, winreg.REG_SZ, "Local")
				winreg.SetValueEx(key_handle, "FileSysPath", 0, winreg.REG_SZ, rf"{os.environ['SystemRoot']}\System32\GroupPolicy\Machine")
				winreg.SetValueEx(key_handle, "DisplayName", 0, winreg.REG_SZ, GPO_NAME)
				winreg.SetValueEx(key_handle, "GPOName", 0, winreg.REG_SZ, GPO_NAME)
				winreg.SetValueEx(key_handle, "PSScriptOrder", 0, winreg.REG_DWORD, 1)

				with winreg.CreateKeyEx(key_handle, "0", 0, winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key_handle2:
					winreg.SetValueEx(key_handle2, "Script", 0, winreg.REG_SZ, script_path)
					winreg.SetValueEx(key_handle2, "Parameters", 0, winreg.REG_SZ, script_params)
					winreg.SetValueEx(key_handle2, "ErrorCode", 0, winreg.REG_DWORD, 0)
					winreg.SetValueEx(key_handle2, "IsPowershell", 0, winreg.REG_DWORD, 0)
					winreg.SetValueEx(
						key_handle2, "ExecTime", 0, winreg.REG_BINARY, b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
					)

		with winreg.CreateKeyEx(
			winreg.HKEY_LOCAL_MACHINE,
			r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
			0,
			winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY,
		) as key_handle:
			winreg.SetValueEx(key_handle, "MaxGPOScriptWait", 0, winreg.REG_DWORD, 0)
			# winreg.SetValueEx(key_handle, "ShutdownWithoutLogon", 0, winreg.REG_DWORD, 1)


def setup_system() -> None:
	if sys.platform != "win32":
		return None

	logger.notice("Setting WebDAV WebClient parameters")
	import winreg

	with winreg.CreateKeyEx(
		winreg.HKEY_LOCAL_MACHINE,
		r"SYSTEM\CurrentControlSet\Services\WebClient\Parameters",
		0,
		winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY,
	) as key_handle:
		winreg.SetValueEx(key_handle, "FileSizeLimitInBytes", 0, winreg.REG_DWORD, 0xFFFFFFFF)


def cleanup_control_server_files() -> None:
	share_dir = Path(config.get("control_server", "files_dir"))
	if not share_dir.exists():
		logger.info("Creating files directory %s", share_dir)
		share_dir.mkdir(parents=True)
	for content in share_dir.iterdir():
		if content.is_file():
			logger.debug("Deleting file %s", content)
			content.unlink()


def setup(full: bool = False, options: Namespace | None = None) -> None:
	if not options:
		options = Namespace()
	logger.notice("Running opsiclientd setup")
	errors = []

	if full:
		opsi_service_setup(options)
		try:
			install_service()
		except Exception as err:
			logger.error("Failed to install service: %s", err, exc_info=True)
			errors.append(str(err))

	try:
		setup_ssl(full)
	except Exception as err:
		logger.error("Failed to setup ssl: %s", err, exc_info=True)
		errors.append(str(err))

	try:
		cleanup_registry_uninstall()
	except Exception as err:
		logger.error("Failed to clean cleanup_registry_uninstall: %s", err, exc_info=True)
		errors.append(str(err))

	if not config.get("control_server", "skip_setup_firewall"):
		try:
			setup_firewall()
		except Exception as err:
			logger.error("Failed to setup firewall: %s", err, exc_info=True)
			errors.append(str(err))

	try:
		setup_system()
	except Exception as err:
		logger.error("Failed to setup system: %s", err, exc_info=True)
		errors.append(str(err))

	try:
		setup_on_shutdown()
	except Exception as err:
		logger.error("Failed to setup on_shutdown: %s", err, exc_info=True)
		errors.append(str(err))

	try:
		cleanup_control_server_files()
	except Exception as err:
		logger.error("Failed to clean control server files: %s", err, exc_info=True)

	try:
		cleanup_registry_environment_path()
	except Exception as err:
		logger.error("Failed to clean registry environment PATH: %s", err, exc_info=True)

	logger.notice("Setup completed with %d errors", len(errors))
	if errors and full:
		raise RuntimeError(", ".join(errors))
