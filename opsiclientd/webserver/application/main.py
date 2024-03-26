# -*- coding: utf-8 -*-

# This file is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2023-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

from opsiclientd.webserver.application import set_opsiclientd
from opsiclientd.webserver.application.index import setup_index

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd


def setup_application(opsiclientd: Opsiclientd) -> FastAPI:
	set_opsiclientd(opsiclientd)
	app = FastAPI()
	setup_index(app)
	return app
