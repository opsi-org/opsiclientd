# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
"""
Non-free parts of opsiclientd.
"""

import base64
import time
from hashlib import md5
from typing import Any

from Crypto.Hash import MD5
from Crypto.Signature import pkcs1_15
from OPSI.Util import getPublicKey  # type: ignore[import]
from opsicommon.logging import get_logger

logger = get_logger()


def verify_modules(backend_info: dict[str, Any], needed_modules: list[str] | None = None) -> None:
	logger.debug("Verifying modules file signature")
	modules = backend_info["modules"]
	helpermodules = backend_info["realmodules"]
	needed_modules = needed_modules or []

	if not modules.get("customer"):
		raise RuntimeError("No customer in modules file")

	if not modules.get("valid"):
		raise RuntimeError("Modules file invalid")

	for needed_module in needed_modules:
		if not modules.get(needed_module):
			raise RuntimeError(f"Module {needed_module} currently disabled")

	if (
		modules.get("expires", "") != "never"
		and time.mktime(time.strptime(modules.get("expires", "2000-01-01"), "%Y-%m-%d")) - time.time() <= 0
	):
		raise RuntimeError("Modules file expired")

	public_key = getPublicKey(
		data=base64.decodebytes(
			b"AAAAB3NzaC1yc2EAAAADAQABAAABAQCAD/I79Jd0eKwwfuVwh5B2z+S8aV0C5suItJa18RrYip+d4P0ogzqoCfOoVWtDo"
			b"jY96FDYv+2d73LsoOckHCnuh55GA0mtuVMWdXNZIE8Avt/RzbEoYGo/H0weuga7I8PuQNC/nyS8w3W8TH4pt+ZCjZZoX8"
			b"S+IizWCYwfqYoYTMLgB0i+6TCAfJj3mNgCrDZkQ24+rOFS4a8RrjamEz/b81noWl9IntllK1hySkR+LbulfTGALHgHkDU"
			b"lk0OSu+zBPw/hcDSOMiDQvvHfmR4quGyLPbQ2FOVm1TzE0bQPR+Bhx4V8Eo2kNYstG2eJELrz7J1TJI0rCjpB+FQjYPsP"
		)
	)
	data = ""
	mks = list(modules.keys())
	mks.sort()
	for module in mks:
		if module in ("valid", "signature"):
			continue
		if module in helpermodules:
			val = helpermodules[module]
			if int(val) > 0:
				modules[module] = True
		else:
			val = modules[module]
			if isinstance(val, bool):
				val = "yes" if val else "no"
		data += f"{module.lower().strip()} = {val}\r\n"

	verified = False
	if modules["signature"].startswith("{"):
		s_bytes = int(modules["signature"].split("}", 1)[-1]).to_bytes(256, "big")
		try:
			pkcs1_15.new(public_key).verify(MD5.new(data.encode()), s_bytes)
			verified = True
		except ValueError:
			# Invalid signature
			pass
	else:
		h_int = int.from_bytes(md5(data.encode()).digest(), "big")
		s_int = public_key._encrypt(int(modules["signature"]))
		verified = h_int == s_int

	if not verified:
		raise RuntimeError("Modules file invalid")

	logger.info("Modules file signature verified (customer: %s)", modules.get("customer"))
