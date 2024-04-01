# -*- coding: utf-8 -*-

# This file is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2023-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

import asyncio
import datetime
import re
import threading
import time

import msgspec
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from opsicommon.exceptions import BackendAuthenticationError, BackendPermissionDeniedError
from opsicommon.logging import LEVEL_TO_NAME, OPSI_LEVEL_TO_LEVEL, get_logger
from starlette.endpoints import WebSocketEndpoint
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocket

from opsiclientd.Config import Config
from opsiclientd.webserver.application.middleware import Session

LOG_VIEWER_PAGE = """<!DOCTYPE html>
<html>
<head>
	<title>opsiclientd - log viewer</title>
	<link rel="stylesheet" href="/static/opsiclientd.css" />
	<script src="/static/javascript/log_viewer.js"></script>
	<script src="/static/javascript/msgpack.js"></script>
	<script>
		function onLoad() {
			startLog(20000);
		}
	</script>
</head>
<body onload="onLoad();">
	<div id="log-settings">
		<div class="log-setting">
			<label for="log-level-filter">Filter by level:</label>
			<input id="log-level-filter" type="number" min="1" max="9" value="9" onchange="applyLevelFilter(this.value);">
		</div>
		<div class="log-setting">
			<label for="log-context-filter">Filter by context:</label>
			<input id="log-context-filter" type="text" onchange="applyContextFilter(this.value);"/>
		</div>
		<div class="log-setting">
			<label for="log-message-filter">Filter by message:</label>
			<input id="log-message-filter" type="text" onchange="applyMessageFilter(this.value);"/>
		</div>
		<div class="log-setting">
			<label for="collapse-all">Collapse multi-line:</label>
			<input type="checkbox" id="collapse-all" onclick="collapseAll(this.checked);" checked>
		</div>
		<div class="log-setting">
			<label for="collapse-all">Auto scroll:</label>
			<input type="checkbox" id="auto-scroll" onclick="setAutoScroll(this.checked);" checked>
		</div>
		<div class="log-setting">
			<label>Font size:</label>
			<button id="decrease-font-size" onclick="changeFontSize(-1);">-</button>
			<button id="increase-font-size" onclick="changeFontSize(+1);">+</button>
		</div>
	</div>
	<div id="log-container" onwheel="if (window.event.deltaY < 0) setAutoScroll(false);">
		<div id="log-line-container" style="font-size: 14px"></div>
		<div id="log-msg-container"></div>
	</div>
</body>
</html>
"""

logger = get_logger()
config = Config()
log_viewer_router = APIRouter()


class LogReaderThread(threading.Thread):
	record_start_regex = re.compile(r"^\[(\d)\]\s\[([\d\-\:\. ]+)\]\s\[([^\]]*)\]\s(.*)$")
	is_record_start_regex = re.compile(r"^\[\d\]\s\[")  # should speed up matching
	max_delay = 0.2
	max_record_buffer_size = 2500

	def __init__(self, filename: str, loop: asyncio.AbstractEventLoop, websocket: WebSocket, num_tail_records=-1):
		super().__init__(daemon=True, name="LogReaderThread")
		self.should_stop = False
		self.filename = filename
		self.loop = loop
		self.websocket = websocket
		self.num_tail_records = int(num_tail_records)
		self.record_buffer = []
		self.send_time = 0
		self._initial_read = False

	def send_buffer(self):
		if not self.record_buffer:
			return
		data = b""
		for record in self.record_buffer:
			data += msgspec.msgpack.encode(record)

		asyncio.run_coroutine_threadsafe(self.websocket.send_bytes(data), self.loop)
		self.send_time = time.time()
		self.record_buffer = []

	def send_buffer_if_needed(self, max_delay=None):
		if max_delay is None:
			max_delay = self.max_delay
		if self.record_buffer and (len(self.record_buffer) > self.max_record_buffer_size or time.time() - self.send_time > max_delay):
			self.send_buffer()

	def parse_log_line(self, line):
		match = self.record_start_regex.match(line)
		if not match:
			if self.record_buffer:
				self.record_buffer[-1]["msg"] += f"\n{line.rstrip()}"
			return None
		context = {}
		cnum = 0
		for val in match.group(3).split(","):
			context[cnum] = val.strip()
		opsilevel = int(match.group(1))
		lvl = OPSI_LEVEL_TO_LEVEL[opsilevel]
		levelname = LEVEL_TO_NAME[lvl]
		created = datetime.datetime.strptime(match.group(2), "%Y-%m-%d %H:%M:%S.%f")
		return {
			"created": created.timestamp(),
			"context": context,
			"levelname": levelname,
			"opsilevel": opsilevel,
			"msg": match.group(4),
			"exc_text": None,
		}

	def add_log_line(self, line):
		if not line:
			return
		record = self.parse_log_line(line)
		if record:
			self.record_buffer.append(record)

	def stop(self):
		self.should_stop = True

	def _get_start_position(self):
		if self.num_tail_records <= 0:
			return 0

		record_to_position = {}
		record_number = 0
		with open(self.filename, "rb") as file:
			position = 0
			for line in file:
				if self.is_record_start_regex.match(line.decode("utf-8", "replace")):
					record_number += 1
					record_to_position[record_number] = position
				position += len(line)

		if record_number <= self.num_tail_records:
			start_record = 1
			start_position = 0
		else:
			start_record = record_number - self.num_tail_records + 1
			start_position = record_to_position.get(start_record, 0)

		logger.info("Setting log file start position to %d, record %d/%d", start_position, start_record, record_number)
		return start_position

	def run(self):
		try:
			start_position = self._get_start_position()
			with open(self.filename, "r", encoding="utf-8", errors="replace") as file:
				logger.debug("Start reading log file %s", self.filename)
				file.seek(start_position)
				self._initial_read = True
				# Start sending big bunches (high delay)
				max_delay = 3
				line_buffer = []
				no_line_count = 0

				while not self.should_stop:
					line = file.readline()
					if line:
						no_line_count = 0
						line_buffer.append(line)
						if len(line_buffer) >= 2 and self.is_record_start_regex.match(line_buffer[-1]):
							# Last line is a new record, not continuation text
							# Add all lines, except the last one
							for i in range(len(line_buffer) - 1):
								self.add_log_line(line_buffer[i])
							line_buffer = [line_buffer[-1]]
							self.send_buffer_if_needed(max_delay)
					else:
						if self._initial_read:
							self._initial_read = False
							max_delay = self.max_delay
						no_line_count += 1
						if no_line_count > 1:
							# Add all lines
							for line in line_buffer:
								self.add_log_line(line)
							line_buffer = []
							self.send_buffer_if_needed(max_delay)
						time.sleep(self.max_delay / 3)
		except Exception as err:
			logger.error("Error in log reader thread: %s", err, exc_info=True)


@log_viewer_router.get("/")
def index_page() -> HTMLResponse:
	return HTMLResponse(LOG_VIEWER_PAGE)


@log_viewer_router.websocket_route("/ws")
class LoggerWebsocket(WebSocketEndpoint):
	encoding = "bytes"
	record_start_regex = re.compile(r"^\[(\d)\]\s\[([\d\-\:\. ]+)\]\s\[([^\]]*)\]\s(.*)$")
	is_record_start_regex = re.compile(r"^\[\d\]\s\[")  # should speed up matching
	max_delay = 0.2
	max_record_buffer_size = 2500

	def __init__(self, scope: Scope, receive: Receive, send: Send) -> None:
		super().__init__(scope, receive, send)
		self._scope = scope
		self._log_reader_thread: LogReaderThread | None = None
		self.filename = config.get("global", "log_file")

	async def _check_authorization(self) -> None:
		session = self._scope.get("session")
		if not session or not isinstance(session, Session):
			raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail=f"Access to {self}, no valid session found")

		if not session.authenticated:
			raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail=f"Access to {self}, not authenticated")

	async def on_connect(
		self, websocket: WebSocket, client: str | None = None, start_time: str | int | None = None, num_records: int | None = None
	) -> None:
		await self._check_authorization()

		try:
			num_records = int(num_records)
		except (ValueError, TypeError):
			num_records = -1
		logger.info("Websocket client is starting to read log stream: num_records=%s, client=%s", num_records, client)
		await websocket.accept()
		self._log_reader_thread = LogReaderThread(
			filename=self.filename, loop=asyncio.get_event_loop(), websocket=websocket, num_tail_records=num_records
		)
		self._log_reader_thread.start()

	async def on_disconnect(self, websocket: WebSocket, close_code: int) -> None:
		if self._log_reader_thread:
			self._log_reader_thread.stop()


def setup(app: FastAPI) -> None:
	app.include_router(log_viewer_router, prefix="/log_viewer")
