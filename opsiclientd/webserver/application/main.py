# -*- coding: utf-8 -*-

# This file is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2023-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

from opsiclientd.webserver.application import set_opsiclientd
from opsiclientd.webserver.application.control import setup as setup_control_interface
from opsiclientd.webserver.application.index import setup as setup_index
from opsiclientd.webserver.application.log_viewer import setup as setup_log_viewer
from opsiclientd.webserver.application.middleware import BaseMiddleware

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd


def setup_application(opsiclientd: Opsiclientd) -> FastAPI:
	set_opsiclientd(opsiclientd)
	app = FastAPI()
	app.add_middleware(BaseMiddleware)
	setup_index(app)
	setup_control_interface(app)
	setup_log_viewer(app)
	return app
