# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
opsiclientd.messagebus.process
"""

from __future__ import annotations

import asyncio
import locale
import platform
import re
import subprocess
from asyncio import AbstractEventLoop
from asyncio.subprocess import PIPE
from asyncio.subprocess import Process as AsyncioProcess
from threading import Lock, Thread
from time import sleep, time
from typing import Awaitable, Callable

from opsicommon.logging import logger  # type: ignore[import]
from opsicommon.messagebus import (
	CONNECTION_USER_CHANNEL,
	Error,
	ProcessDataReadMessage,
	ProcessDataWriteMessage,
	ProcessErrorMessage,
	ProcessMessage,
	ProcessStartEventMessage,
	ProcessStartRequestMessage,
	ProcessStopEventMessage,
	ProcessStopRequestMessage,
)

processes: dict[str, Process] = {}
processes_lock = Lock()


class Process(Thread):
	block_size = 8192

	def __init__(self, command: list[str], send_message_function: Callable, process_start_request: ProcessStartRequestMessage) -> None:
		Thread.__init__(self, daemon=True)
		self._command = command
		self._proc: AsyncioProcess | None = None
		self._loop: AbstractEventLoop = asyncio.new_event_loop()
		self.send_message: Callable = send_message_function
		self._process_start_request = process_start_request

	@property
	def process_id(self) -> str:
		return self._process_start_request.process_id

	@property
	def response_channel(self) -> str:
		return self._process_start_request.response_channel

	def stop(self) -> None:
		logger.info("Stopping %r", self)
		if self._proc:
			self._proc.kill()
		try:
			self.wait_for_stop()
		except TimeoutError as error:
			logger.error("Failed to wait for stop of %r: %s", self, error, exc_info=False)

	def wait_for_stop(self, timeout: int = 10.0) -> None:
		current_time = time()
		while time() < current_time + timeout:
			if not self.is_alive():
				logger.debug("Thread %r finished", self)
				return
			sleep(0.2)
		raise TimeoutError(f"Reached timeout of {timeout}s while waiting for process-thread to terminate.")

	def write_stdin(self, data: bytes) -> None:
		asyncio.run_coroutine_threadsafe(self._write_stdin(data), self._loop)

	async def _stdout_reader(self) -> None:
		assert self._proc and self._proc.stdout
		while True:
			data = await self._proc.stdout.read(self.block_size)
			if not data:
				break
			message = ProcessDataReadMessage(
				sender=CONNECTION_USER_CHANNEL, channel=self.response_channel, process_id=self.process_id, stdout=data
			)
			await self.send_message(message)

	async def _stderr_reader(self) -> None:
		assert self._proc and self._proc.stderr
		while True:
			data = await self._proc.stderr.read(self.block_size)
			if not data:
				break
			message = ProcessDataReadMessage(
				sender=CONNECTION_USER_CHANNEL, channel=self.response_channel, process_id=self.process_id, stderr=data
			)
			await self.send_message(message)

	async def _write_stdin(self, data: bytes) -> None:
		assert self._proc and self._proc.stdin
		self._proc.stdin.write(data)
		await self._proc.stdin.drain()

	async def _arun(self) -> None:
		logger.notice("Received ProcessStartRequestMessage %r", self)
		message: ProcessMessage
		try:
			if self._process_start_request.shell:
				self._proc = await asyncio.create_subprocess_shell(" ".join(self._command), stdin=PIPE, stdout=PIPE, stderr=PIPE)
			else:
				self._proc = await asyncio.create_subprocess_exec(*self._command, stdin=PIPE, stdout=PIPE, stderr=PIPE)
		except Exception as error:  # pylint: disable=broad-except
			logger.error(error, exc_info=True)
			message = ProcessErrorMessage(
				sender=CONNECTION_USER_CHANNEL,
				channel=self.response_channel,
				process_id=self.process_id,
				error=Error(message=str(error)),
			)
			await self.send_message(message)
			return

		encoding = locale.getencoding()
		if platform.system().lower() == "windows":  # windows suggests cp1252 even if using something else like cp850
			try:
				output = subprocess.check_output("chcp", shell=True).decode("ascii", errors="replace")
				match = re.search(r": (\d+)", output)
				if match:
					codepage = int(match.group(1))
					encoding = f"cp{codepage}"
			except Exception as error:  # pylint: disable=broad-except
				logger.info("Failed to determine codepage, using default. %s", error)

		message = ProcessStartEventMessage(
			sender=CONNECTION_USER_CHANNEL,
			channel=self.response_channel,
			process_id=self.process_id,
			back_channel="$",
			local_process_id=self._proc.pid,
			locale_encoding=encoding,
		)
		await self.send_message(message)
		logger.info("Started %r", self)
		await asyncio.gather(self._stderr_reader(), self._stdout_reader())
		exit_code = await self._proc.wait()  # necessary because stderr and stdout might be closed prematurely
		try:
			message = ProcessStopEventMessage(
				sender=CONNECTION_USER_CHANNEL, channel=self.response_channel, process_id=self.process_id, exit_code=exit_code
			)
			await self.send_message(message)
		except Exception as err:  # pylint: disable=broad-except
			logger.error(err, exc_info=True)
		finally:
			with processes_lock:
				if self.process_id in processes:
					del processes[self.process_id]

	def run(self) -> None:
		self._loop.run_until_complete(self._arun())
		self._loop.close()

	def __repr__(self) -> str:
		return f"Process(command={self._command}, id={self.process_id}, shell={self._process_start_request.shell})"

	def __str__(self) -> str:
		info = "running"
		if self._proc and self._proc.returncode:
			info = f"finished - exit code {self._proc.returncode}"
		return f"{self._command[0]} ({info})"


def process_messagebus_message(message: ProcessMessage, send_message: Callable, async_send_message: Awaitable) -> None:
	with processes_lock:
		process = processes.get(message.process_id)

	try:
		if isinstance(message, ProcessStartRequestMessage):
			if not process:
				with processes_lock:
					process = Process(message.command, send_message_function=async_send_message, process_start_request=message)
					processes[message.process_id] = process
					processes[message.process_id].start()
			else:
				raise RuntimeError(f"Process already open: {process!r}")
			return
		if isinstance(message, ProcessDataWriteMessage):
			process.write_stdin(message.stdin)
			return
		if isinstance(message, ProcessStopRequestMessage):
			process.stop()
			return
		raise RuntimeError("Invalid process id")
	except Exception as err:  # pylint: disable=broad-except
		logger.warning(err, exc_info=True)
		if process:
			process.stop()
		else:
			msg = ProcessErrorMessage(
				sender=CONNECTION_USER_CHANNEL,
				channel=message.response_channel,
				process_id=message.process_id,
				error=Error(message=str(err)),
			)
			send_message(msg)


def stop_running_processes() -> None:
	for process_id in list(processes.keys()):
		processes[process_id].stop()
