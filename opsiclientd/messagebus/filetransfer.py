# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
opsiclientd.messagebus.filetransfer
"""

from __future__ import annotations

from contextvars import copy_context
from pathlib import Path
from queue import Empty, Queue
from threading import Lock, Thread
from time import time
from typing import Callable

from opsicommon.logging import get_logger
from opsicommon.messagebus import CONNECTION_USER_CHANNEL
from opsicommon.messagebus.message import (
	Error,
	FileChunkMessage,
	FileErrorMessage,
	FileMessage,
	FileUploadRequestMessage,
	FileUploadResultMessage,
	MessageErrorEnum,
	MessageType,
)

from opsiclientd.messagebus.terminal import terminals

file_uploads_lock = Lock()
file_uploads: dict[str, FileUpload] = {}

logger = get_logger("opsiclientd")


class FileUpload(Thread):
	chunk_timeout = 300

	def __init__(self, send_message_function: Callable, file_upload_request: FileUploadRequestMessage) -> None:
		super().__init__()
		self.daemon = True
		self._context = copy_context()
		self._should_stop = False
		self._message_queue: Queue[FileMessage] = Queue()
		self._file_upload_request = file_upload_request
		self._send_message_function = send_message_function
		self._chunk_number = 0
		self._last_chunk_time = time()

		if not self._file_upload_request.name:
			raise ValueError("Invalid name")
		if not self._file_upload_request.content_type:
			raise ValueError("Invalid content_type")

		destination_path: Path | None = None
		if self._file_upload_request.destination_dir:
			destination_path = Path(self._file_upload_request.destination_dir)
		elif self._file_upload_request.terminal_id:
			terminal = terminals.get(self._file_upload_request.terminal_id)
			if terminal:
				destination_path = terminal.get_cwd()
		if not destination_path:
			raise ValueError("Invalid destination_dir")

		self._file_path: Path = (destination_path / self._file_upload_request.name).absolute()
		if not self._file_path.is_relative_to(destination_path):
			raise ValueError("Invalid name")

		orig_name = self._file_path.name
		ext = 0
		while self._file_path.exists():
			ext += 1
			self._file_path = self._file_path.with_name(f"{orig_name}.{ext}")
		self._file_path.touch()
		self._file_path.chmod(0o660)

	def _error(self, error: str):
		self._file_path.unlink(missing_ok=True)
		msg = FileErrorMessage(
			sender=CONNECTION_USER_CHANNEL,
			channel=self._file_upload_request.response_channel,
			file_id=self._file_upload_request.file_id,
			error=Error(message=error, details=None),
		)
		self._send_message_function(msg)

	def process_message(self, message: FileMessage) -> None:
		if message.type != MessageType.FILE_CHUNK:
			raise ValueError(f"Received invalid message type {message.type}")
		self._message_queue.put(message)

	def _run(self) -> None:
		for var in self._context:
			var.set(self._context[var])
		while not self._should_stop:
			try:
				message = self._message_queue.get(timeout=1.0)
			except Empty:
				if time() > self._last_chunk_time + self.chunk_timeout:
					logger.notice("File transfer timed out")
					msg = FileErrorMessage(
						sender=CONNECTION_USER_CHANNEL,
						channel=self._file_upload_request.response_channel,
						file_id=self._file_upload_request.file_id,
						error=Error(
							message="File transfer timed out while waiting for next chunk",
							details=None,
							code=MessageErrorEnum.TIMEOUT_REACHED,
						),
					)
					self._send_message_function(msg)
					self._should_stop = True
				continue
			if not isinstance(message, FileChunkMessage):
				logger.warning("Expected FileChungMessage, but received message type %r", message.type)
				continue

			logger.debug("Received file chunk %r", message.number)
			self._last_chunk_time = time()
			if message.number != self._chunk_number + 1:
				self._error(f"Expected chunk number {self._chunk_number + 1}")

			with open(self._file_path, mode="ab") as file:
				file.write(message.data)

			self._chunk_number = message.number

			if message.last:
				logger.debug("Last chunk received")
				fur_message = FileUploadResultMessage(
					sender=CONNECTION_USER_CHANNEL,
					channel=self._file_upload_request.response_channel,
					file_id=self._file_upload_request.file_id,
					path=str(self._file_path),
				)
				self._send_message_function(fur_message)
				self._should_stop = True

	def run(self) -> None:
		try:
			self._run()
		except Exception as err:
			logger.error(err, exc_info=True)


def process_messagebus_message(message: FileMessage, send_message: Callable) -> None:
	with file_uploads_lock:
		file_upload = file_uploads.get(message.file_id)
	try:
		if isinstance(message, FileUploadRequestMessage):
			with file_uploads_lock:
				if file_upload:
					raise RuntimeError("File id already taken")
				file_uploads[message.file_id] = FileUpload(send_message_function=send_message, file_upload_request=message)
				file_uploads[message.file_id].start()
				return

		if not file_upload:
			raise RuntimeError("Invalid file id")

		file_upload.process_message(message)

	except Exception as err:
		logger.warning(err, exc_info=True)

		msg = FileErrorMessage(
			sender=CONNECTION_USER_CHANNEL,
			channel=message.response_channel,
			file_id=message.file_id,
			error=Error(message=str(err), details=None),
		)
		send_message(msg)
