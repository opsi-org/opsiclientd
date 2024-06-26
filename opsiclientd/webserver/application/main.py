# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

from opsiclientd.Config import Config
from opsiclientd.webserver.application import set_opsiclientd
from opsiclientd.webserver.application.cache_service import setup as setup_cache_service
from opsiclientd.webserver.application.control import setup as setup_control_interface
from opsiclientd.webserver.application.download import setup as setup_download
from opsiclientd.webserver.application.index import setup as setup_index
from opsiclientd.webserver.application.info import setup as setup_info
from opsiclientd.webserver.application.kiosk import setup as setup_kiosk
from opsiclientd.webserver.application.log_viewer import setup as setup_log_viewer
from opsiclientd.webserver.application.middleware import BaseMiddleware
from opsiclientd.webserver.application.terminal import setup as setup_terminal
from opsiclientd.webserver.application.upload import setup as setup_upload

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd

config = Config()


def setup_application(opsiclientd: Opsiclientd) -> FastAPI:
	set_opsiclientd(opsiclientd)
	app = FastAPI()
	app.add_middleware(BaseMiddleware)
	setup_index(app)
	setup_info(app)
	setup_upload(app)
	setup_download(app)
	setup_control_interface(app)
	setup_log_viewer(app)
	setup_terminal(app)
	setup_cache_service(app)
	if config.get("control_server", "kiosk_api_active"):
		setup_kiosk(app)
	return app
