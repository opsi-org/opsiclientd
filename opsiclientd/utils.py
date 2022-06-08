# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
utils
"""

import struct

import netifaces
from opsicommon.logging import logger


def get_include_exclude_product_ids(config_service, includeProductGroupIds, excludeProductGroupIds):
	includeProductIds = []
	excludeProductIds = []

	logger.debug("Given includeProductGroupIds: '%s'", includeProductGroupIds)
	logger.debug("Given excludeProductGroupIds: '%s'", excludeProductGroupIds)

	if includeProductGroupIds:
		includeProductIds = [
			obj.objectId for obj in
			config_service.objectToGroup_getObjects(groupType="ProductGroup", groupId=includeProductGroupIds)  # pylint: disable=no-member
		]
		logger.debug("Only products ids %s will be regarded.", includeProductIds)

	if excludeProductGroupIds:
		excludeProductIds = [
			obj.objectId for obj in
			config_service.objectToGroup_getObjects(groupType="ProductGroup", groupId=excludeProductGroupIds)  # pylint: disable=no-member
		]
		logger.debug("Product ids %s will be excluded.", excludeProductIds)

	return includeProductIds, excludeProductIds


def lo_word(dword):
	return str(dword & 0x0000ffff)


def hi_word(dword):
	return str(dword >> 16)


def read_fixed_file_info(data):
	# https://docs.microsoft.com/en-us/windows/win32/api/verrsrc/ns-verrsrc-vs_fixedfileinfo
	pos = data.find(b"\xBD\x04\xEF\xFE")
	if pos < 0:
		raise ValueError("Failed to read VS_FIXEDFILEINFO")
	vms = struct.unpack("<I", data[pos + 8:pos + 12])[0]
	vls = struct.unpack("<I", data[pos + 12:pos + 16])[0]
	return ".".join([hi_word(vms), lo_word(vms), hi_word(vls), lo_word(vls)])


def get_version_from_mach_binary(filename):
	from macholib import MachO  # pylint: disable=import-outside-toplevel

	machofile = MachO.MachO(filename)
	fpc_offset, fpc_size = 0, 0
	for (_load_cmd, _cmd, _data) in machofile.headers[0].commands:
		for data in _data:
			if data and hasattr(data, "sectname") and data.sectname:
				sectname = data.sectname.rstrip(b'\0')
				if sectname == b"fpc.resources":
					fpc_offset = data.offset
					fpc_size = data.size

	if fpc_offset > 0:
		with open(filename, "rb") as file:
			file.seek(fpc_offset)
			return read_fixed_file_info(file.read(fpc_size))

	raise ValueError(f"No version information embedded in '{filename}'")


def get_version_from_elf_binary(filename):
	from elftools.elf.elffile import ELFFile  # pylint: disable=import-outside-toplevel

	with open(filename, 'rb') as file:
		elffile = ELFFile(file)
		for section in elffile.iter_sections():
			if section.name == "fpc.resources":
				return read_fixed_file_info(section.data())

	raise ValueError(f"No version information embedded in '{filename}'")


def get_version_from_dos_binary(filename):
	import pefile  # pylint: disable=import-outside-toplevel

	try:
		pef = pefile.PE(filename)
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


def log_network_status():
	status_string = ""
	for interface in netifaces.interfaces():  # pylint: disable=c-extension-no-member
		for protocol in (netifaces.AF_INET, netifaces.AF_INET6):  # pylint: disable=c-extension-no-member
			af_inet_list = netifaces.ifaddresses(interface).get(protocol, {})  # pylint: disable=c-extension-no-member
			if af_inet_list:
				for entry in af_inet_list:
					status_string += f"Interface {interface}, Address {entry.get('addr')}, Netmask {entry.get('netmask')}\n"
	logger.info("Current network Status:\n%s", status_string)

