# -*- coding: utf-8 -*-

# This file is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2023-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd

_opsiclientd: Opsiclientd | None = None


def get_opsiclientd() -> Opsiclientd:
	assert _opsiclientd
	return _opsiclientd


def set_opsiclientd(opsiclientd: Opsiclientd) -> None:
	global _opsiclientd
	_opsiclientd = opsiclientd
