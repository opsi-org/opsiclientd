
# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
opsiclientd.messagebus.filetransfer
"""

from __future__ import annotations

from multiprocessing.util import is_abstract_socket_namespace
from pathlib import Path
from typing import Callable, Dict

from opsicommon.logging import logger  # type: ignore[import]
from opsicommon.messagebus import (  # type: ignore[import]
	FileUploadRequestMessage,
	FileUploadResultMessage,
	Message,
	MessageType,
)

from opsiclientd.messagebus.terminal import terminals

file_uploads: Dict[str, FileUpload] = {}


class FileUpload:  # pylint: disable=too-few-public-methods
	def __init__(
		self,
		send_message_function: Callable,
		file_upload_request: FileUploadRequestMessage
	) -> None:
		self._file_upload_request = file_upload_request
		self._send_message_function = send_message_function
		self._chunk_number = 0

		if not self._file_upload_request.name:
			raise ValueError("Invalid name")
		if not self._file_upload_request.content_type:
			raise ValueError("Invalid content_type")

		destination_dir = None
		if self._file_upload_request.destination_dir:
			destination_dir = self._file_upload_request.destination_dir
		elif self._file_upload_request.terminal_id:
			terminal = terminals.get(self._file_upload_request.terminal_id)
			if terminal:
				destination_dir = terminal.get_cwd()
		if not destination_dir:
			raise ValueError("Invalid destination_dir")

		destination_path = Path(destination_dir)
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
		msg = FileUploadResultMessage(
			sender="@",
			channel=self._file_upload_request.back_channel,
			file_id=self._file_upload_request.file_id,
			error={
				"code": 0,
				"message": error,
				"details": None,
			}
		)
		self._send_message_function(msg)

	def process_message(self, message: Message) -> None:
		if message.type == MessageType.FILE_CHUNK:
			logger.debug("Received file chunk %r", message.number)
			if message.number != self._chunk_number + 1:
				self._error(f"Expected chunk number {self._chunk_number + 1}")

			with open(self._file_path, mode="ab") as file:
				file.write(message.data)

			self._chunk_number = message.number

			if message.last:
				logger.debug("Last chunk received")
				msg = FileUploadResultMessage(
					sender="@",
					channel=self._file_upload_request.back_channel,
					file_id=self._file_upload_request.file_id,
					path=str(self._file_path)
				)
				self._send_message_function(msg)
		else:
			raise ValueError(f"Received invalid message type {message.type}")


def process_messagebus_message(message: Message, send_message: Callable) -> None:
	file_upload = file_uploads.get(message.file_id)
	try:
		if message.type == MessageType.FILE_UPLOAD_REQUEST:
			if file_upload:
				raise RuntimeError("File id already taken")
			file_uploads[message.file_id] = FileUpload(
				send_message_function=send_message,
				file_upload_request=message
			)
			return

		if not file_upload:
			raise RuntimeError("Invalid file id")

		file_upload.process_message(message)

	except Exception as err:  # pylint: disable=broad-except
		logger.warning(err, exc_info=True)

		msg = FileUploadResultMessage(
			sender="@", channel=message.back_channel, file_id=message.file_id, error={
				"code": 0,
				"message": str(err),
				"details": None,
			}
		)
		send_message(msg)
