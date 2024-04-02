# -*- coding: utf-8 -*-

# This file is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2023-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

import asyncio
import threading
import time
from typing import Callable

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from opsicommon.logging import get_logger
from opsicommon.system.info import is_windows
from starlette.endpoints import WebSocketEndpoint
from starlette.status import HTTP_401_UNAUTHORIZED
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocket

from opsiclientd.Config import Config
from opsiclientd.webserver.application.middleware import Session

TERMINAL_PAGE = """<!DOCTYPE html>
<html>
<head>
	<title>opsiclientd - terminal</title>
	<link rel="stylesheet" href="/static/opsiclientd.css" />
	<link rel="stylesheet" href="/static/xterm/xterm.css" />
	<script src="/static/xterm/xterm.js"></script>
	<script src="/static/xterm/fit.js"></script>
	<script src="/static/xterm/fullscreen.js"></script>
	<script src="/static/xterm/search.js"></script>
	<script src="/static/xterm/webLinks.js"></script>
	<script>
		let term;
		let ws;
		let utf8Encoder = new TextEncoder();

		function runTerminal() {
			Terminal.applyAddon(fullscreen)
			Terminal.applyAddon(fit)
			Terminal.applyAddon(search)
			Terminal.applyAddon(webLinks)
			term = new Terminal({
				cursorBlink: true,
				macOptionIsMeta: true,
				scrollback: 1000,
				fontSize: 14,
				//lineHeight: 1.1
			});
			term.open(document.getElementById('terminal'));
			term.fit()
			//term.resize(columns, lines)
			console.log(`size: ${term.cols} columns, ${term.rows} rows`)

			term.on('key', (key, ev) => {
				//console.debug("pressed key", key);
				//console.debug("event", ev);
				ws.send(utf8Encoder.encode(key));
			});

			term.on('paste', function (data, ev) {
				ws.send(data);
			});

			let params = [`lines=${term.rows}`, `columns=${term.cols}`]
			let loc = window.location;
			let ws_uri;
			if (loc.protocol == "https:") {
				ws_uri = "wss:";
			} else {
				ws_uri = "ws:";
			}
			ws_uri += "//" + loc.host;
			ws = new WebSocket(ws_uri + "/terminal/ws?" + params.join('&'));

			ws.onmessage = function (evt) {
				evt.data.text().then(text => {
					//console.debug(text);
					term.write(text);
				});
			};

			ws.onclose = function() {
				console.log("Terminal ws connection closed...");
			};
		}
	</script>
</head>
<body style="background-color: #000000; margin: 5px;" onload="runTerminal();">
	<!--
	<button onclick="term.setOption('fontSize', term.getOption('fontSize') + 1);">+</button>
	<button onclick="term.setOption('fontSize', term.getOption('fontSize') - 1);">-</button>
	-->
	<div style="width: 100%; height: 100%; position: absolute; margin:auto;" id="terminal"></div>
</body>
</html>
"""

logger = get_logger()
config = Config()
terminal_router = APIRouter()


class TerminalReaderThread(threading.Thread):
	def __init__(self, loop: asyncio.AbstractEventLoop, websocket: WebSocket, child_read: Callable) -> None:
		super().__init__(daemon=True, name="TerminalReaderThread")
		self.loop = loop
		self.websocket = websocket
		self.child_read = child_read
		self.should_stop = False

	def run(self):
		while not self.should_stop:
			try:
				data = self.child_read(16 * 1024)
				if not data:  # EOF.
					break
				if not self.should_stop:
					asyncio.run_coroutine_threadsafe(self.websocket.send_bytes(data), self.loop)
				time.sleep(0.001)
			# except socket.timeout:
			# continue
			except (IOError, EOFError) as err:
				logger.debug(err)
				break
			except Exception as err:
				if not self.should_stop:
					logger.error("Error in terminal reader thread: %s %s", err.__class__, err, exc_info=True)
					time.sleep(1)

	def stop(self):
		self.should_stop = True


@terminal_router.get("/")
def index_page() -> HTMLResponse:
	return HTMLResponse(TERMINAL_PAGE)


@terminal_router.websocket_route("/ws")
class TerminalWebsocket(WebSocketEndpoint):
	encoding = "bytes"

	def __init__(self, scope: Scope, receive: Receive, send: Send) -> None:
		super().__init__(scope, receive, send)
		self._scope = scope
		self.terminal_reader_thread: TerminalReaderThread | None = None
		self.child_pid: int | None = None
		self.child_read: Callable | None = None
		self.child_write: Callable | None = None
		self.child_set_size: Callable | None = None
		self.child_stop: Callable | None = None

	async def _check_authorization(self) -> None:
		session = self._scope.get("session")
		if not session or not isinstance(session, Session):
			raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail=f"Access to {self}, no valid session found")

		if not session.authenticated:
			raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail=f"Access to {self}, not authenticated")

	async def on_connect(self, websocket: WebSocket, shell: str | None = None, lines: int | None = 30, columns: int | None = 120) -> None:
		await self._check_authorization()

		if not shell:
			shell = "powershell.exe" if is_windows() else "bash"
		try:
			lines = int(lines)
		except (ValueError, TypeError):
			lines = 30
		try:
			columns = int(columns)
		except (ValueError, TypeError):
			columns = 120

		if is_windows():
			from opsiclientd.windows import start_pty
		else:
			from opsiclientd.posix import start_pty

		logger.notice("Starting terminal shell=%s, lines=%d, columns=%d", shell, lines, columns)
		await websocket.accept()

		try:
			(
				self.child_pid,
				self.child_read,
				self.child_write,
				self.child_set_size,
				self.child_stop,
			) = start_pty(shell=shell, lines=lines, columns=columns)
			self.terminal_reader_thread = TerminalReaderThread(
				loop=asyncio.get_event_loop(), websocket=websocket, child_read=self.child_read
			)
			self.terminal_reader_thread.start()
		except Exception as err:
			websocket.close(code=500, reason=str(err))

	async def on_disconnect(self, websocket: WebSocket, close_code: int) -> None:
		if self.terminal_reader_thread:
			self.terminal_reader_thread.stop()
		self.child_pid = None
		self.child_read = None
		self.child_write = None
		self.child_set_size = None
		self.child_stop = None

	async def on_receive(self, websocket: WebSocket, data: bytes) -> None:
		if self.child_write:
			self.child_write(data)


def setup(app: FastAPI) -> None:
	app.include_router(terminal_router, prefix="/terminal")
