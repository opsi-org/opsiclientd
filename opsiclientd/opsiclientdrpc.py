# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
opsiclientd rpc client
"""

import argparse
import os
import platform
import sys
from typing import NoReturn

from opsi import __version__ as python_opsi_version
from opsi.logging import LOG_DEBUG, LOG_NONE, get_logger, log_context, logging_config, secret_filter
from opsi.opsi.service.client import ServiceClient, set_rpc_timeout

# Do not remove this import, it's needed by using this module from CLI
from opsi_legacy import System  # noqa

from opsiclientd import DEFAULT_FILE_LOG_FORMAT, __version__

logger = get_logger()


def get_opsi_host_key() -> str:
	config_file = "/etc/opsi-client-agent/opsiclientd.conf"
	if platform.system().lower() == "windows":
		config_file = os.path.join(
			os.environ.get("PROGRAMFILES(X86)", os.environ.get("PROGRAMFILES", "c:\\Program Files")),
			"opsi.org",
			"opsi-client-agent",
			"opsiclientd",
			"opsiclientd.conf",
		)

	with open(config_file, "r", encoding="utf-8") as file:
		for line in file:
			line = line.strip()
			if line.startswith("opsi_host_key"):
				return line.split("=", 1)[-1].strip()

	raise RuntimeError(f"Failed to find opsi_host_key in config file {config_file}")


class ArgumentParser(argparse.ArgumentParser):
	def error(self, message: str) -> NoReturn:
		if len(sys.argv) in (5, 6):
			raise DeprecationWarning("Legacy comandline arguments")
		argparse.ArgumentParser.error(self, message)


def main() -> None:
	with log_context({"instance": os.path.basename(sys.argv[0])}):
		parser = ArgumentParser()
		parser.add_argument("--version", action="version", version=f"{__version__} [python-opsi={python_opsi_version}]")
		parser.add_argument(
			"--log-level",
			default=LOG_NONE,
			type=int,
			choices=range(10),
			help=(
				"Set the log level. "
				"0: nothing, 1: essential, 2: critical, 3: errors, 4: warnings, 5: notices "
				"6: infos, 7: debug messages, 8: trace messages, 9: secrets"
			),
		)
		parser.add_argument("--log-file", help="Set log file")
		parser.add_argument("--address", default="https://127.0.0.1:4441/opsiclientd", help="Set service address")
		parser.add_argument("--username", help="Username to use for service connection.")
		parser.add_argument("--password", help="Password to use for service connection (default: opsi host key).")
		parser.add_argument("--timeout", type=int, default=30, help="Read timeout for the rpc in seconds (default: 30).")
		parser.add_argument("rpc", help="The remote procedure call to execute.")

		log_file = None
		log_level = None
		address = None
		username = None
		password = None
		rpc = None
		timeout = 30
		try:
			args = parser.parse_args()
			log_file = args.log_file
			log_level = args.log_level
			address = args.address
			username = args.username
			password = args.password
			rpc = args.rpc
			timeout = max(0, args.timeout)
			if not username and not password:
				try:
					password = get_opsi_host_key()
					secret_filter.add_secrets(password)
				except Exception as err:
					raise RuntimeError(f"Failed to read opsi host key from config file: {err}") from err

		except DeprecationWarning:
			# Fallback to legacy comandline arguments
			# <username> <password> <port> [debug-log-file] <rpc>
			(username, password, port, rpc) = sys.argv[1:5]
			secret_filter.add_secrets(password)
			address = f"https://127.0.0.1:{port}/opsiclientd"
			if len(sys.argv) > 5:
				log_level = LOG_DEBUG
				log_file = sys.argv[4]
				rpc = sys.argv[5]

		logging_config(log_file=log_file, file_level=log_level, stderr_level=LOG_NONE, file_format=DEFAULT_FILE_LOG_FORMAT)

		logger.info("opsiclientdrpc version=%s [python-opsi=%s]", __version__, python_opsi_version)
		logger.debug(
			"log_file=%s, log_level=%s, address=%s, username=%s, password=%s, rpc=%s", log_file, log_level, address, username, password, rpc
		)

		try:
			service_client = ServiceClient(
				address=address, username=username, password=password, verify="accept_all", jsonrpc_create_methods=True, max_time_diff=30.0
			)
			service_client.connect()
			method = rpc.split("(", 1)[0]
			set_rpc_timeout(method, timeout)
			logger.notice(f"Executing: {rpc}")
			result = eval(f"service_client.{rpc}")
			print(result)
		except Exception as err:
			logger.error(err, exc_info=True)
			print(f"Error: {err}", file=sys.stderr)
			sys.exit(1)
