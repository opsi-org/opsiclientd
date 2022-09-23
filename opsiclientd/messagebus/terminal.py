
# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
opsiclientd.messagebus.terminal
"""

from __future__ import annotations

from pathlib import Path
from threading import Thread
from time import sleep
from typing import Callable, Dict, Optional

from opsicommon.logging import logger  # type: ignore[import]
from opsicommon.messagebus import (  # type: ignore[import]
	Message,
	MessageType,
	TerminalCloseEvent,
	TerminalDataRead,
	TerminalOpenEvent,
	TerminalResizeEvent,
)
from psutil import AccessDenied, NoSuchProcess, Process

from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS

if RUNNING_ON_WINDOWS:
	from opsiclientd.windows import start_pty
else:
	from opsiclientd.posix import start_pty

terminals: Dict[str, Terminal] = {}


class TerminalReaderThread(Thread):
	block_size = 16 * 1024

	def __init__(self, terminal: Terminal):
		super().__init__()
		self.daemon = True
		self.should_stop = False
		self.terminal = terminal

	def run(self):
		while not self.should_stop:
			try:
				data = self.terminal.pty_read(self.block_size)
				if not data:  # EOF.
					break
				if not self.should_stop:
					message = TerminalDataRead(  # pylint: disable=unexpected-keyword-arg,no-value-for-parameter
						sender=self.terminal.sender, channel=self.terminal.channel, terminal_id=self.terminal.id, data=data
					)
					self.terminal.send_message(message)  # pylint: disable=no-member
				sleep(0.001)
			except (IOError, EOFError) as err:
				logger.debug(err)
				self.terminal.close()
				break
			except Exception as err:  # pylint: disable=broad-except
				if not self.should_stop:
					logger.error("Error in terminal reader thread: %s %s", err.__class__, err, exc_info=True)
					self.terminal.close()
					break

	def stop(self):
		self.should_stop = True


class Terminal:  # pylint: disable=too-many-instance-attributes
	default_rows = 30
	max_rows = 100
	default_cols = 120
	max_cols = 300

	def __init__(  # pylint: disable=too-many-arguments
		self,
		send_message: Callable,
		id: str,  # pylint: disable=invalid-name,redefined-builtin
		owner: str,
		sender: str,
		channel: str,
		rows: int = None,
		cols: int = None,
		shell: str = None
	) -> None:
		self.send_message = send_message
		self.id = id  # pylint: disable=invalid-name
		self.owner = owner
		self.sender = sender
		self.channel = channel
		self.rows = self.default_rows
		self.cols = self.default_cols

		self.set_size(rows, cols, False)

		if not shell:
			shell = "cmd.exe" if RUNNING_ON_WINDOWS else "bash"
		(self.pty_pid, self.pty_read, self.pty_write, self.pty_set_size, self.pty_stop) = start_pty(  # pylint: disable=attribute-defined-outside-init
			shell=shell, lines=self.rows, columns=self.cols
		)
		self.terminal_reader_thread = TerminalReaderThread(self)  # pylint: disable=attribute-defined-outside-init
		self._closing = False

	def start_reading(self):
		if not self.terminal_reader_thread.is_alive():
			self.terminal_reader_thread.start()

	def set_size(self, rows: int = None, cols: int = None, pty_set_size: bool = True) -> None:
		self.rows = min(max(1, int(rows or self.default_rows)), self.max_rows)
		self.cols = min(max(1, int(cols or self.default_cols)), self.max_cols)
		if pty_set_size:
			self.pty_set_size(self.rows, self.cols)

	def process_message(self, message: Message) -> None:
		if message.type == MessageType.TERMINAL_DATA_WRITE:
			self.pty_write(message.data)
		elif message.type == MessageType.TERMINAL_RESIZE_REQUEST:
			self.set_size(message.rows, message.cols)
			message = TerminalResizeEvent(  # pylint: disable=unexpected-keyword-arg,no-value-for-parameter
				sender=self.sender,
				channel=self.channel,
				terminal_id=self.id,
				rows=self.rows,
				cols=self.cols,
			)
			self.send_message(message)
		elif message.type == MessageType.TERMINAL_CLOSE_REQUEST:
			self.close()
		else:
			logger.warning("Received invalid message type %r", message.type)

	def close(self) -> None:
		if self._closing:
			return
		logger.info("Close terminal")
		self._closing = True
		try:
			if self.terminal_reader_thread:
				self.terminal_reader_thread.stop()
			message = TerminalCloseEvent(
				sender=self.sender, channel=self.channel, terminal_id=self.id
			)
			self.send_message(message)
			self.pty_stop()
			if self.id in terminals:
				del terminals[self.id]
		except Exception as err:  # pylint: disable=broad-except
			logger.error(err, exc_info=True)

	def get_cwd(self) -> Optional[Path]:
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


def process_messagebus_message(message: Message, send_message: Callable) -> None:
	terminal = terminals.get(message.terminal_id)

	try:
		if message.type == MessageType.TERMINAL_OPEN_REQUEST:
			if not terminal:
				terminal = Terminal(
					send_message=send_message,
					id=message.terminal_id,
					owner=message.sender,
					sender="@",
					channel=message.back_channel,
					rows=message.rows,
					cols=message.cols,
					shell=message.shell,
				)
				terminals[terminal.id] = terminal
			else:
				# Resize to redraw screen
				terminals[terminal.id].set_size(message.rows - 1, message.cols)
				terminals[terminal.id].set_size(message.rows, message.cols)
			msg = TerminalOpenEvent(  # pylint: disable=unexpected-keyword-arg,no-value-for-parameter
				sender="@",
				channel=message.back_channel,
				terminal_id=terminal.id,
				back_channel="$",
				rows=terminal.rows,
				cols=terminal.cols,
			)
			send_message(msg)
			terminal.start_reading()
			return
		if terminal:
			terminal.process_message(message)
			return
		raise RuntimeError("Invalid terminal id")
	except Exception as err:  # pylint: disable=broad-except
		logger.warning(err, exc_info=True)
		if terminal:
			terminal.close()
		else:
			msg = TerminalCloseEvent(
				sender="@", channel=message.back_channel, terminal_id=message.terminal_id, error={
					"code": 0,
					"message": str(err),
					"details": None,
				}
			)
			send_message(msg)
