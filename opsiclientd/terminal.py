# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
opsiclientd.terminal
"""

from threading import Thread
from time import sleep
from typing import Callable, Dict

from opsicommon.logging import logger  # type: ignore[import]
from opsicommon.messagebus import (  # type: ignore[import]
	Message,
	MessageType,
	TerminalCloseEvent,
	TerminalDataRead,
	TerminalOpenEvent,
	TerminalResizeEvent,
)

from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS

if RUNNING_ON_WINDOWS:
	from opsiclientd.windows import start_pty
else:
	from opsiclientd.posix import start_pty

terminals: Dict[str, "Terminal"] = {}


class TerminalReaderThread(Thread):
	block_size = 16 * 1024

	def __init__(self, terminal: "Terminal"):
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

		self.set_size(rows, cols)

		if not shell:
			shell = "cmd.exe" if RUNNING_ON_WINDOWS else "bash"
		(self.pty_read, self.pty_write, self.pty_set_size, self.pty_stop) = start_pty(  # pylint: disable=attribute-defined-outside-init
			shell=shell, lines=self.rows, columns=self.cols
		)
		self.terminal_reader_thread = TerminalReaderThread(self)  # pylint: disable=attribute-defined-outside-init
		self._closing = False

	def start_reading(self):
		if not self.terminal_reader_thread.is_alive():
			self.terminal_reader_thread.start()

	def set_size(self, rows: int = None, cols: int = None) -> None:
		self.rows = min(max(1, int(rows or self.default_rows)), self.max_rows)
		self.cols = min(max(1, int(cols or self.default_cols)), self.max_cols)

	def process_message(self, message: Message) -> None:
		if message.type == MessageType.TERMINAL_DATA_WRITE:
			self.pty_write(message.data)
		elif message.type == MessageType.TERMINAL_RESIZE_REQUEST:
			self.rows = message.rows
			self.cols = message.cols
			self.pty_set_size(self.rows, self.cols)
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
			message = TerminalCloseEvent(  # pylint: disable=unexpected-keyword-arg,no-value-for-parameter
				sender=self.sender, channel=self.channel, terminal_id=self.id
			)
			self.send_message(message)
			self.pty_stop()
			if self.id in terminals:
				del terminals[self.id]
		except Exception as err:  # pylint: disable=broad-except
			logger.error(err, exc_info=True)


def process_messagebus_message(message: Message, send_message: Callable) -> None:
	terminal = terminals.get(message.terminal_id)
	if terminal and terminal.owner != message.sender:
		return
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
	else:
		if terminal:
			terminal.process_message(message)
		else:
			msg = TerminalCloseEvent(  # pylint: disable=unexpected-keyword-arg,no-value-for-parameter
				sender="@", channel=message.back_channel, terminal_id=message.terminal_id
			)
			send_message(msg)
