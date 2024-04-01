# -*- coding: utf-8 -*-

# This file is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2023-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

from __future__ import annotations

from threading import Thread
from typing import TYPE_CHECKING

from opsicommon.logging import get_logger
from uvicorn.config import Config as UvicornConfig
from uvicorn.server import Server as UvicornServer

from opsiclientd import __version__
from opsiclientd.webserver.application.main import setup_application

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd

logger = get_logger()


class Webserver(Thread):
	def __init__(self, opsiclientd: Opsiclientd) -> None:
		super().__init__(daemon=True, name="Webserver")

		self.opsiclientd = opsiclientd
		self._server: UvicornServer | None
		self._server_thread: Thread | None

		app = setup_application(self.opsiclientd)

		uvicorn_config = UvicornConfig(
			app=app,
			interface="asgi3",
			http="h11",
			# TODO:
			host="0.0.0.0",  ###self.opsiclientd.config.get("control_server", "interface"),
			port=self.opsiclientd.config.get("control_server", "port"),
			workers=1,
			log_config=None,
			date_header=False,
			server_header=False,
			headers=[("Server", f"opsiclientd {__version__}")],
			ws_ping_interval=15,
			ws_ping_timeout=10,
			ssl_keyfile=self.opsiclientd.config.get("control_server", "ssl_server_key_file"),
			ssl_certfile=self.opsiclientd.config.get("control_server", "ssl_server_cert_file"),
		)
		self._server = UvicornServer(config=uvicorn_config)

	def run(self) -> None:
		try:
			logger.debug("Starting uvicorn server")
			assert self._server
			self._server.run()
			logger.debug("Uvicorn server stopped")
		except Exception as err:
			logger.error("Webserver error: %s", err, exc_info=True)

	def stop(self) -> None:
		if self._server:
			self._server.should_exit = True
		self.join(5)
