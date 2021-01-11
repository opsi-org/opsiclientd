# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2019 uib GmbH <info@uib.de>

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

import codecs
import os
import sys
import argparse
import platform

from OPSI.Backend.JSONRPC import JSONRPCBackend
# Do not remove this import, it's needed by using this module from CLI
from OPSI import System # pylint: disable=unused-import
from OPSI import __version__ as python_opsi_version

from opsicommon.logging import (
	logger, init_logging, log_context, secret_filter, LOG_DEBUG, LOG_NONE
)

from opsiclientd import __version__, DEFAULT_FILE_LOG_FORMAT

def get_opsi_host_key():
	config_file = "/etc/opsi-client-agent/opsiclientd.conf"
	if platform.system().lower() == 'windows':
		config_file = os.path.join(
			os.environ.get("PROGRAMFILES(X86)", os.environ.get("PROGRAMFILES")),
			"opsi.org", "opsi-client-agent", "opsiclientd", "opsiclientd.conf"
		)

	with codecs.open(config_file, "r", "utf-8") as file:
		for line in file.readlines():
			line = line.strip()
			if line.startswith("opsi_host_key"):
				return line.split("=", 1)[-1].strip()

	raise RuntimeError(f"Failed to find opsi_host_key in config file {config_file}")

class ArgumentParser(argparse.ArgumentParser):
	def error(self, message):
		if len(sys.argv) in (5, 6):
			raise DeprecationWarning("Legacy comandline arguments")
		return argparse.ArgumentParser.error(self, message)

def main():
	with log_context({'instance' : os.path.basename(sys.argv[0])}):
		parser = ArgumentParser()
		parser.add_argument('--version',
			action='version',
			version=f"{__version__} [python-opsi={python_opsi_version}]"
		)
		parser.add_argument('--log-level',
			default=LOG_NONE,
			type=int,
			choices=range(0, 10),
			help=(
				"Set the log level. "
				"0: nothing, 1: essential, 2: critical, 3: errors, 4: warnings, 5: notices "
				"6: infos, 7: debug messages, 8: trace messages, 9: secrets"
			)
		)
		parser.add_argument('--log-file',
			help="Set log file"
		)
		parser.add_argument('--address',
			default="https://localhost:4441/opsiclientd",
			help="Set service address"
		)
		parser.add_argument('--username',
			help="Username to use for service connection."
		)
		parser.add_argument('--password',
			help="Password to use for service connection (default: opsi host key)."
		)
		parser.add_argument('rpc',
			help="The remote procedure call to execute."
		)

		log_file = None
		log_level = None
		address = None
		username = None
		password = None
		rpc = None
		try:
			args = parser.parse_args()
			log_file = args.log_file
			log_level = args.log_level
			address = args.address
			username = args.username
			password = args.password
			rpc = args.rpc
			if not username and not password:
				try:
					password = get_opsi_host_key()
					secret_filter.add_secrets([password])
				except Exception as err: # pylint: disable=broad-except
					raise RuntimeError(f"Failed to read opsi host key from config file: {err}") from err

		except DeprecationWarning:
			# Fallback to legacy comandline arguments
			# <username> <password> <port> [debug-log-file] <rpc>
			(username, password, port, rpc) = sys.argv[1:5] # pylint: disable=unbalanced-tuple-unpacking
			secret_filter.add_secrets([password])
			address = f"https://localhost:{port}/opsiclientd"
			if len(sys.argv) > 5:
				log_level = LOG_DEBUG
				log_file = sys.argv[4]
				rpc = sys.argv[5]

		init_logging(
			log_file=log_file,
			file_level=log_level,
			stderr_level=LOG_NONE,
			file_format=DEFAULT_FILE_LOG_FORMAT
		)

		logger.debug(
			"log_file=%s, log_level=%s, address=%s, username=%s, password=%s, rpc=%s",
			log_file, log_level, address, username, password, rpc
		)

		try:
			with JSONRPCBackend(
				username=username,
				password=password,
				address=address
			) as jsonrpc: # pylint: disable=unused-variable
				logger.notice(f"Executing: {rpc}")
				result = eval(f"jsonrpc.{rpc}") # pylint: disable=eval-used
				print(result)
		except Exception as err: # pylint: disable=broad-except
			logger.error(err, exc_info=True)
			print(f"Error: {err}", file=sys.stderr)
			sys.exit(1)
