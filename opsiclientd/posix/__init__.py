# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

import os
import pty
import fcntl
import struct
import signal
import termios
import subprocess

def start_pty(shell="bash", lines=30, columns=120):
	(child_pid, child_fd) = pty.fork()
	if child_pid == 0:
		subprocess.call(shell)
	else:
		winsize = struct.pack("HHHH", lines, columns, 0, 0)
		fcntl.ioctl(child_fd, termios.TIOCSWINSZ, winsize)

		def stop():
			os.close(child_fd)
			os.kill(child_pid, signal.SIGTERM)
			#time.sleep(3)
			#os.kill(child_pid, signal.SIGKILL)
		
		def read(length: int):
			return os.read(child_fd, length)
		
		def write(data: bytes):
			return os.write(child_fd, data)
		
		return (read, write, stop)
