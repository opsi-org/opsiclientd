# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
opsiclientd.messagebus.terminal
"""

from __future__ import annotations

from contextvars import copy_context
from pathlib import Path
from queue import Empty, Queue
from threading import Lock, Thread
from time import sleep, time
from typing import Callable

from opsicommon.logging import get_logger
from opsicommon.messagebus import CONNECTION_USER_CHANNEL
from opsicommon.messagebus.message import (
	Error,
	MessageType,
	TerminalCloseEventMessage,
	TerminalCloseRequestMessage,
	TerminalDataReadMessage,
	TerminalDataWriteMessage,
	TerminalErrorMessage,
	TerminalMessage,
	TerminalOpenEventMessage,
	TerminalOpenRequestMessage,
	TerminalResizeEventMessage,
	TerminalResizeRequestMessage,
)
from psutil import AccessDenied, NoSuchProcess, Process  # type: ignore[import]

from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS

if RUNNING_ON_WINDOWS:
	from opsiclientd.windows import start_pty
else:
	from opsiclientd.posix import start_pty


terminals: dict[str, Terminal] = {}
terminals_lock = Lock()

logger = get_logger()


class TerminalReaderThread(Thread):
	block_size = 16 * 1024

	def __init__(self, terminal: Terminal) -> None:
		super().__init__()
		self.daemon = True
		self._context = copy_context()
		self._should_stop = False
		self.terminal = terminal

	def run(self) -> None:
		for var in self._context:
			var.set(self._context[var])
		while not self._should_stop:
			try:
				data = self.terminal.pty_read(self.block_size)
				if not data:  # EOF.
					break
				if not self._should_stop:
					message = TerminalDataReadMessage(
						sender=CONNECTION_USER_CHANNEL,
						channel=self.terminal.back_channel,
						terminal_id=self.terminal.terminal_id,
						data=data,
					)
					self.terminal.send_message(message)
				sleep(0.001)
			except (IOError, EOFError) as err:
				logger.debug(err)
				self.terminal.close()
				break
			except Exception as err:
				if not self._should_stop:
					logger.error(
						"Error in terminal reader thread: %s %s",
						err.__class__,
						err,
						exc_info=True,
					)
					self.terminal.close()
					break

	def stop(self) -> None:
		self._should_stop = True


class Terminal(Thread):
	default_rows = 30
	max_rows = 100
	default_cols = 120
	max_cols = 300
	idle_timeout = 600

	def __init__(
		self,
		send_message_function: Callable,
		terminal_open_request: TerminalOpenRequestMessage,
	) -> None:
		super().__init__()
		self.daemon = True
		self._context = copy_context()
		self._should_stop = False
		self._message_queue: Queue[TerminalMessage] = Queue()
		self._terminal_open_request = terminal_open_request
		self.send_message = self._send_message_function = send_message_function
		self.rows = self.default_rows
		self.cols = self.default_cols
		self._last_usage = time()

		self.set_size(terminal_open_request.rows, terminal_open_request.cols, False)

		shell = self._terminal_open_request.shell
		if not shell:
			shell = "cmd.exe" if RUNNING_ON_WINDOWS else "bash"
		(
			self.pty_pid,
			self.pty_read,
			self.pty_write,
			self.pty_set_size,
			self.pty_stop,
		) = start_pty(shell=shell, lines=self.rows, columns=self.cols)
		self.terminal_reader_thread = TerminalReaderThread(self)

	@property
	def terminal_id(self) -> str:
		return self._terminal_open_request.terminal_id

	@property
	def back_channel(self) -> str:
		return self._terminal_open_request.response_channel

	def set_size(self, rows: int | None = None, cols: int | None = None, pty_set_size: bool = True) -> None:
		self.rows = min(max(1, int(rows or self.default_rows)), self.max_rows)
		self.cols = min(max(1, int(cols or self.default_cols)), self.max_cols)
		if pty_set_size:
			self.pty_set_size(self.rows, self.cols)

	def process_message(self, message: TerminalMessage) -> None:
		if message.type not in (
			MessageType.TERMINAL_DATA_WRITE,
			MessageType.TERMINAL_RESIZE_REQUEST,
			MessageType.TERMINAL_CLOSE_REQUEST,
		):
			logger.warning("Received invalid message type %r", message.type)
			return
		self._message_queue.put(message)

	def run(self) -> None:
		try:
			self._run()
		except Exception as err:
			logger.error(err, exc_info=True)

	def close(self) -> None:
		if self._should_stop:
			return
		logger.info("Close terminal")
		self._should_stop = True
		try:
			if self.terminal_reader_thread:
				self.terminal_reader_thread.stop()
			message = TerminalCloseEventMessage(sender=CONNECTION_USER_CHANNEL, channel=self.back_channel, terminal_id=self.terminal_id)
			self._send_message_function(message)
			self.pty_stop()
			if self.terminal_id in terminals:
				del terminals[self.terminal_id]
		except Exception as err:
			logger.error(err, exc_info=True)

	def get_cwd(self) -> Path | None:
		try:
			proc = Process(self.pty_pid)
		except (NoSuchProcess, ValueError):
			return None

		cwd = proc.cwd()
		for child in proc.children(recursive=True):
			try:
				cwd = child.cwd()
			except AccessDenied:
				# Child owned by an other user (su)
				pass
		return Path(cwd)

	def _run(self) -> None:
		for var in self._context:
			var.set(self._context[var])
		toe_message = TerminalOpenEventMessage(
			sender=CONNECTION_USER_CHANNEL,
			channel=self.back_channel,
			terminal_id=self.terminal_id,
			back_channel="$",
			rows=self.rows,
			cols=self.cols,
		)
		self._send_message_function(toe_message)
		self.terminal_reader_thread.start()
		while not self._should_stop:
			try:
				message = self._message_queue.get(timeout=1.0)
			except Empty:
				if time() > self._last_usage + self.idle_timeout:
					logger.notice("Terminal timed out")
					self.close()
				continue
			self._last_usage = time()
			if isinstance(message, TerminalDataWriteMessage):
				self.pty_write(message.data)
			elif isinstance(message, TerminalResizeRequestMessage):
				self.set_size(message.rows, message.cols)
				message = TerminalResizeEventMessage(
					sender=CONNECTION_USER_CHANNEL,
					channel=self.back_channel,
					terminal_id=self.terminal_id,
					rows=self.rows,
					cols=self.cols,
				)
				self._send_message_function(message)
			elif isinstance(message, TerminalCloseRequestMessage):
				self.close()


def process_messagebus_message(message: TerminalMessage, send_message: Callable) -> None:
	with terminals_lock:
		terminal = terminals.get(message.terminal_id)

	try:
		if isinstance(message, TerminalOpenRequestMessage):
			if not terminal:
				with terminals_lock:
					terminal = Terminal(
						send_message_function=send_message,
						terminal_open_request=message,
					)
					terminals[message.terminal_id] = terminal
					terminals[message.terminal_id].start()
			else:
				# Resize to redraw screen
				if message.rows and message.cols:
					terminals[message.terminal_id].set_size(message.rows - 1, message.cols)
					terminals[message.terminal_id].set_size(message.rows, message.cols)
			return
		if terminal:
			terminal.process_message(message)
			return
		raise RuntimeError("Invalid terminal id")
	except Exception as err:
		logger.warning(err, exc_info=True)
		if terminal:
			terminal.close()
		else:
			msg = TerminalErrorMessage(
				sender=CONNECTION_USER_CHANNEL,
				channel=message.response_channel,
				terminal_id=message.terminal_id,
				error=Error(message=str(err), details=None),
			)
			send_message(msg)
