# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
utils
"""

from __future__ import annotations

import os
import platform
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from opsi.logging import get_logger
from opsi.system.network import get_network_info

from opsiclientd.Config import Config
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS

if os.name == "nt":
	import winreg

	import win32file
if TYPE_CHECKING:
	from opsiclientd.OpsiService import ServiceClient

config = Config()


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
			for obj in config_service.objectToGroup_getObjects(groupType="ProductGroup", groupId=includeProductGroupIds)  # ty: ignore[unresolved-attribute]
		]
		logger.debug("Only products ids %s will be regarded", includeProductIds)

	if excludeProductGroupIds:
		excludeProductIds = [
			obj.objectId
			for obj in config_service.objectToGroup_getObjects(groupType="ProductGroup", groupId=excludeProductGroupIds)  # ty: ignore[unresolved-attribute]
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
	from macholib import MachO

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
	from elftools.elf.elffile import ELFFile

	with open(filename, "rb") as file:
		elffile = ELFFile(file)
		for section in elffile.iter_sections():
			if section.name == "fpc.resources":
				return read_fixed_file_info(section.data())

	raise ValueError(f"No version information embedded in '{filename}'")


def get_version_from_dos_binary(filename: str | Path) -> str:
	import pefile

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


def get_mshotfix_package_name() -> str | None:
	if not RUNNING_ON_WINDOWS:
		return None

	arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
	releaseId = ""
	currentBuild = 0
	subKey = "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion"
	try:
		currentBuild = int(get_registry_value(subKey, "CurrentBuild"))
	except Exception as reg_err:
		logger.error("Failed to read registry value %s %s: %s", subKey, "CurrentBuild", reg_err)
	try:
		releaseId = get_registry_value(subKey, "ReleaseID")
	except Exception as reg_err:
		logger.error("Failed to read registry value %s %s: %s", subKey, "ReleaseID", reg_err)

	releasePackageName = None
	if currentBuild >= 10000 and currentBuild < 20000:  # win10
		# Setting default to 1507-Build
		if not releaseId:
			releaseId = "1507"
		releasePackageName = f"mshotfix-win10-{releaseId}-{arch}-glb"
	elif currentBuild == 20348:
		releasePackageName = "mshotfix-win2022"
	elif currentBuild == 22000:
		releasePackageName = "mshotfix-win11-21h2"
	elif currentBuild in (22621, 22631):  # 22h2 and 22h2 with enablement package
		releasePackageName = "mshotfix-win11-22h2"
	elif currentBuild in (26100, 26200):  # 24h2 and 25h2
		releasePackageName = "mshotfix-win11-24h2"
	elif currentBuild > 26200:
		logger.warning("Unknown windows build %s. Maybe update opsi-client-agent. Using fallback mshotfix-win11-24h2", currentBuild)
		releasePackageName = "mshotfix-win11-24h2"
	else:
		logger.warning("Unknown windows build %s. Using fallback mshotfix-win10-1507-x64-glb", currentBuild)
		releasePackageName = "mshotfix-win10-1507-x64-glb"

	if arch == "arm64" and "win11" in releasePackageName:
		releasePackageName += "-arm64"  # arm64 specific package for win11
	return releasePackageName


# TODO: move to opsi or opsi-script
def get_registry_value(sub_key: str, value_name: str, root=None) -> str:
	if not RUNNING_ON_WINDOWS:
		raise RuntimeError("Can only access registry on Windows")

	root = root or winreg.HKEY_LOCAL_MACHINE

	flags = winreg.KEY_READ
	flags |= winreg.KEY_WOW64_32KEY if platform.architecture()[0] == "32bit" else winreg.KEY_WOW64_64KEY

	with winreg.OpenKeyEx(root, sub_key, 0, flags) as hkey:
		return winreg.QueryValueEx(hkey, value_name)[0]


# TODO: move to opsi or opsi-script
def set_registry_value(sub_key: str, value_name: str, value: str | int, root=None) -> None:
	if not RUNNING_ON_WINDOWS:
		return

	root = root or winreg.HKEY_LOCAL_MACHINE

	flags = winreg.KEY_WRITE
	flags |= winreg.KEY_WOW64_32KEY if platform.architecture()[0] == "32bit" else winreg.KEY_WOW64_64KEY

	with winreg.CreateKeyEx(root, sub_key, 0, flags) as hkey:
		if isinstance(value, int):
			winreg.SetValueEx(
				hkey,
				value_name,
				0,
				winreg.REG_QWORD if value > 0xFFFFFFFF else winreg.REG_DWORD,
				value,
			)
		else:
			winreg.SetValueEx(hkey, value_name, 0, winreg.REG_SZ, value)
