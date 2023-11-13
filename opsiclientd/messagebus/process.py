
# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
opsiclientd.messagebus.terminal
"""

from __future__ import annotations

import subprocess
from contextvars import copy_context
from queue import Empty, Queue
from threading import Lock, Thread
from time import sleep, time
from typing import Callable

from opsicommon.logging import logger  # type: ignore[import]
from opsicommon.messagebus import (  # type: ignore[import]
	Message,
	MessageType,
	ProcessDataReadMessage,
	ProcessStartEventMessage,
	ProcessStopEventMessage,
	ProcessStartRequestMessage,
)

from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS


processes: dict[str, ProcessThread] = {}
processes_lock = Lock()


class ProcessReaderThread(Thread):
	block_size = 16 * 1024

	def __init__(self, process: ProcessThread):
		super().__init__()
		self.daemon = True
		self._context = copy_context()
		self._should_stop = False
		self.process = process

	def run(self):
		for var in self._context:
			var.set(self._context[var])
		while not self._should_stop:
			try:
				if self.process.process_handle.returncode is not None:
					break
				stdout, stderr = self.process.read_stdouterr(self.block_size)  # TODO: how to read write from/to process?
				if not self._should_stop:
					message = ProcessDataReadMessage(  # pylint: disable=unexpected-keyword-arg,no-value-for-parameter
						sender="@", channel=self.process.back_channel, process_id=self.process.process_id, stdout=stdout, stderr=stderr)
					self.process.send_message(message)  # pylint: disable=no-member
				sleep(1.0)
			except (IOError, EOFError) as err:
				logger.debug(err)
				self.process.close()
				break
			except Exception as err:  # pylint: disable=broad-except
				if not self._should_stop:
					logger.error("Error in terminal reader thread: %s %s", err.__class__, err, exc_info=True)
					self.process.close()
					break

	def stop(self):
		self._should_stop = True


class ProcessThread(Thread):  # pylint: disable=too-many-instance-attributes
	idle_timeout = 600

	def __init__(  # pylint: disable=too-many-arguments
		self,
		send_message_function: Callable,
		process_start_request: ProcessStartRequestMessage
	) -> None:
		super().__init__()
		self.daemon = True
		self._context = copy_context()
		self._should_stop = False
		self._message_queue: Queue[Message] = Queue()
		self._process_start_request = process_start_request
		self.send_message = self._send_message_function = send_message_function
		self._last_usage = time()
		self.local_process_id

		command = self._process_start_request.command
		self.process_handle = subprocess.Popen(command)
		self.local_process_id = self.process_handle.pid
		self.process_reader_thread = ProcessReaderThread(self)

	@property
	def process_id(self) -> str:
		return self._process_start_request.process_id

	@property
	def back_channel(self) -> str:
		return self._process_start_request.back_channel

	def process_message(self, message: Message) -> None:
		if message.type not in (MessageType.PROCESS_DATA_WRITE, MessageType.PROCESS_STOP_REQUEST):
			logger.warning("Received invalid message type %r", message.type)
			return
		self._message_queue.put(message)

	def run(self) -> None:
		try:
			self._run()
		except Exception as err:  # pylint: disable=broad-except
			logger.error(err, exc_info=True)

	def close(self) -> None:
		if self._should_stop:
			return
		logger.info("Stop Process")
		self._should_stop = True
		try:
			if self.process_reader_thread:
				self.process_reader_thread.stop()
			message = ProcessStopEventMessage(
				sender="@", channel=self.back_channel, process_id=self.process_id, exit_code=self.process_handle.returncode
			)
			self._send_message_function(message)
			self.pty_stop()
			if self.process_id in processes:
				del processes[self.process_id]
		except Exception as err:  # pylint: disable=broad-except
			logger.error(err, exc_info=True)

	def _run(self) -> None:
		for var in self._context:
			var.set(self._context[var])
		message = ProcessStartEventMessage(  # pylint: disable=unexpected-keyword-arg,no-value-for-parameter
			sender="@",
			channel=self.back_channel,
			process_id=self.process_id,
			back_channel="$",
			local_process_id=self.local_process_id,
		)
		self._send_message_function(message)
		self.process_reader_thread.start()
		while not self._should_stop:
			try:
				message = self._message_queue.get(timeout=1.0)
			except Empty:
				if time() > self._last_usage + self.idle_timeout:
					logger.notice("Process timed out")
					self.close()
				continue
			self._last_usage = time()
			if message.type == MessageType.PROCESS_DATA_WRITE:
				self.process_handle.communicate(message.stdin)
			elif message.type == MessageType.PROCESS_STOP_REQUEST:
				self.close()


def process_messagebus_message(message: Message, send_message: Callable) -> None:
	with processes_lock:
		process = processes.get(message.process_id)

	try:
		if message.type == MessageType.PROCESS_START_REQUEST:
			if not process:
				with processes_lock:
					process = ProcessThread(
						send_message_function=send_message,
						process_start_request=message
					)
					processes[message.process_id] = process
					processes[message.process_id].start()
			else:
				raise RuntimeError(f"Process with id {message.process_id} already open")
			return
		if process:
			process.process_message(message)
			return
		raise RuntimeError("Invalid process id")
	except Exception as err:  # pylint: disable=broad-except
		logger.warning(err, exc_info=True)
		if process:
			process.close()
		else:
			msg = ProcessStopEventMessage(
				sender="@", channel=message.back_channel, process_id=message.process_id, exit_code=-1, error={
					"code": 0,
					"message": str(err),
					"details": None,
				}
			)
			send_message(msg)
