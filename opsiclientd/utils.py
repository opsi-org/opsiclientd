# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2025 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
utils
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from opsicommon.logging import get_logger
from opsicommon.system.network import get_network_info

from opsiclientd.Config import Config

if os.name == "nt":
	import win32file  # type: ignore[import]

if TYPE_CHECKING:
	from opsiclientd.OpsiService import ServiceClient

config = Config()

PATH_PLACEHOLDERS = {
	"{OPSICLIENTD_LOG_FILE_PATH}": config.get("global", "log_file"),
}

logger = get_logger()


def get_include_exclude_product_ids(
	config_service: ServiceClient, includeProductGroupIds: list[str], excludeProductGroupIds: list[str]
) -> tuple[list[str], list[str]]:
	includeProductIds = []
	excludeProductIds = []

	logger.debug("Given includeProductGroupIds: '%s'", includeProductGroupIds)
	logger.debug("Given excludeProductGroupIds: '%s'", excludeProductGroupIds)

	if includeProductGroupIds:
		includeProductIds = [
			obj.objectId
			for obj in config_service.objectToGroup_getObjects(groupType="ProductGroup", groupId=includeProductGroupIds)  # type: ignore[attr-defined]
		]
		logger.debug("Only products ids %s will be regarded", includeProductIds)

	if excludeProductGroupIds:
		excludeProductIds = [
			obj.objectId
			for obj in config_service.objectToGroup_getObjects(groupType="ProductGroup", groupId=excludeProductGroupIds)  # type: ignore[attr-defined]
		]
		logger.debug("Product ids %s will be excluded", excludeProductIds)

	return includeProductIds, excludeProductIds


def lo_word(dword: int) -> str:
	return str(dword & 0x0000FFFF)


def hi_word(dword: int) -> str:
	return str(dword >> 16)


def read_fixed_file_info(data: bytes) -> str:
	# https://docs.microsoft.com/en-us/windows/win32/api/verrsrc/ns-verrsrc-vs_fixedfileinfo
	pos = data.find(b"\xbd\x04\xef\xfe")
	if pos < 0:
		raise ValueError("Failed to read VS_FIXEDFILEINFO")
	vms = struct.unpack("<I", data[pos + 8 : pos + 12])[0]
	vls = struct.unpack("<I", data[pos + 12 : pos + 16])[0]
	return ".".join([hi_word(vms), lo_word(vms), hi_word(vls), lo_word(vls)])


def get_version_from_mach_binary(filename: str | Path) -> str:
	from macholib import MachO  # type: ignore[import]

	machofile = MachO.MachO(str(filename))
	fpc_offset, fpc_size = 0, 0
	for _load_cmd, _cmd, _data in machofile.headers[0].commands:
		for data in _data:
			if data and hasattr(data, "sectname") and data.sectname:
				sectname = data.sectname.rstrip(b"\0")
				if sectname == b"fpc.resources":
					fpc_offset = data.offset
					fpc_size = data.size

	if fpc_offset > 0:
		with open(filename, "rb") as file:
			file.seek(fpc_offset)
			return read_fixed_file_info(file.read(fpc_size))

	raise ValueError(f"No version information embedded in '{filename}'")


def get_version_from_elf_binary(filename: str | Path) -> str:
	from elftools.elf.elffile import ELFFile  # type: ignore[import]

	with open(filename, "rb") as file:
		elffile = ELFFile(file)  # type: ignore[no-untyped-call]
		for section in elffile.iter_sections():  # type: ignore[no-untyped-call]
			if section.name == "fpc.resources":
				return read_fixed_file_info(section.data())

	raise ValueError(f"No version information embedded in '{filename}'")


def get_version_from_dos_binary(filename: str | Path) -> str:
	import pefile  # type: ignore[import]

	try:
		pef = pefile.PE(str(filename))
		pef.close()
		fileinfo = pef.VS_FIXEDFILEINFO
		if isinstance(fileinfo, list):
			fileinfo = fileinfo[0]
		fvms = fileinfo.FileVersionMS
		fvls = fileinfo.FileVersionLS
		return ".".join([hi_word(fvms), lo_word(fvms), hi_word(fvls), lo_word(fvls)])

	except (AttributeError, pefile.PEFormatError):
		pass
	raise ValueError(f"No version information embedded in '{filename}'")


def log_network_status() -> None:
	status_string = ""
	for interface in get_network_info().interfaces:
		status_string += (
			f"Interface {interface.name}, Address {interface.address}, Family {interface.family}, Netmask {interface.netmask}\n"
		)
	logger.info("Current network Status:\n%s", status_string)


@dataclass
class DiskSpaceUsage:
	capacity: int
	available: int
	used: int
	usage: float


def get_disk_space_usage(path: Path | str) -> DiskSpaceUsage:
	path = str(path)
	if os.name == "nt":
		if len(path) == 1:
			# Assuming a drive letter like "C"
			path = path + ":"

		(sect_per_cluster, bytes_per_sector, free_clusters, total_clusters) = win32file.GetDiskFreeSpace(path)
		capacity = total_clusters * sect_per_cluster * bytes_per_sector
		available = free_clusters * sect_per_cluster * bytes_per_sector
		return DiskSpaceUsage(
			capacity=capacity,
			available=available,
			used=capacity - available,
			usage=(capacity - available) / capacity,
		)

	res = os.statvfs(path)
	return DiskSpaceUsage(
		capacity=res.f_bsize * res.f_blocks,
		available=res.f_bsize * res.f_bavail,
		used=res.f_bsize * (res.f_blocks - res.f_bavail),
		usage=(res.f_blocks - res.f_bavail) / res.f_blocks,
	)


def get_directory_size(path: str | Path) -> int:
	if not isinstance(path, Path):
		path = Path(path)

	if not path.is_dir():
		raise ValueError(f"Path '{path}' is not a directory")

	total_size = 0
	for dirpath, _dirnames, filenames in os.walk(path):
		for filename in filenames:
			try:
				abs_file = os.path.join(dirpath, filename)
				total_size += os.path.getsize(abs_file)
			except (FileNotFoundError, PermissionError):
				# Skip files that can't be accessed
				pass
	return total_size
