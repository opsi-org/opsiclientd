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
opsiclientd Library.

:copyright: uib GmbH <info@uib.de>
:license: GNU Affero General Public License version 3
"""

__version__ = '4.2.0.60'

import os
import sys
import tempfile
import argparse

from opsicommon.logging import (
	logger, logging_config, set_filter_from_string, init_logging as oc_init_logging,
	LOG_NONE, LOG_DEBUG, LOG_ERROR, LOG_NOTICE
)
from OPSI import __version__ as python_opsi_version
from OPSI.System import execute

from opsiclientd.Config import Config
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS

DEFAULT_STDERR_LOG_FORMAT = "%(log_color)s[%(opsilevel)d] [%(asctime)s.%(msecs)03d]%(reset)s [%(contextstring)-40s] %(message)s   (%(filename)s:%(lineno)d)" # pylint: disable=line-too-long
DEFAULT_FILE_LOG_FORMAT = DEFAULT_STDERR_LOG_FORMAT.replace("%(log_color)s", "").replace("%(reset)s", "")

config = Config()

parser = argparse.ArgumentParser()
parser.add_argument(
	"--version", "-V",
	action='version',
	version=f"{__version__} [python-opsi={python_opsi_version}]"
)
parser.add_argument(
	"--log-level", "-l",
	dest="logLevel",
	type=int,
	choices=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
	default=LOG_NOTICE,
	help="Set the log-level."
)
parser.add_argument(
	"--log-filter",
	dest="logFilter",
	default=None,
	help="Filter log records contexts (<ctx-name-1>=<val1>[,val2][;ctx-name-2=val3])."
)

def init_logging(log_dir: str, stderr_level: int = LOG_NONE, log_filter: str = None):
	if not os.path.isdir(log_dir):
		log_dir = tempfile.gettempdir()
	log_file = os.path.join(log_dir, "opsiclientd.log")

	config.set("global", "log_file", log_file)

	log_file_without_ext, ext = os.path.splitext(log_file)

	for i in (9, 8, 7, 6, 5, 4, 3, 2, 1, 0):
		slf = f"{log_file_without_ext}_{i-1}.{ext}"
		olf = f"{log_file_without_ext}.{ext}.{i-1}" # old format
		dlf = f"{log_file_without_ext}_{i}.{ext}"
		if i == 0:
			slf = log_file
		try:
			if i > 0 and os.path.exists(olf):
				# Rename existing log file from old to new format
				os.rename(olf, slf)
			if os.path.exists(slf):
				if os.path.exists(dlf):
					os.unlink(dlf)
				os.rename(slf, dlf)
		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to rename %s to %s: %s", slf, dlf, err)

	oc_init_logging(
		stderr_level=stderr_level,
		stderr_format=DEFAULT_STDERR_LOG_FORMAT,
		log_file=log_file,
		file_level=LOG_DEBUG,
		file_format=DEFAULT_FILE_LOG_FORMAT
	)
	if log_filter:
		set_filter_from_string(log_filter)

	logger.essential("Log file %s started", log_file)

def check_signature(bin_dir):
	logger.info("check_signature is called")
	if not RUNNING_ON_WINDOWS:
		return # Not yet implemented

	windowsVersion = sys.getwindowsversion() # pylint: disable=no-member
	if windowsVersion.major < 6 or (windowsVersion.major == 6 and windowsVersion.minor < 4):
		return # Get-AuthenticodeSignature is only defined for versions since 2016

	binary_list = [
		os.path.join(bin_dir, "opsiclientd.exe"),
		os.path.join(bin_dir, "opsiclientd_rpc.exe"),
		os.path.join(bin_dir, "action_processor_starter.exe")
	]
	for binary in binary_list:
		cmd = f'powershell.exe -ExecutionPolicy Bypass -Command \"(Get-AuthenticodeSignature \'{binary}\').Status -eq \'Valid\'\"'

		result = execute(cmd, captureStderr=True, waitForEnding=True, timeout=20)
		logger.debug(result)
		if not "True" in result:
			raise ValueError(f"Invalid Signature of file {binary}")
	logger.notice("Successfully verified %s", binary_list)
