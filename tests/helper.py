# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

import os
import shutil
import tempfile
from contextlib import contextmanager

@contextmanager
def workInTemporaryDirectory(tempDir=None):
	"""
	Creates a temporary folder to work in. Deletes the folder afterwards.
	:param tempDir: use the given dir as temporary directory. Will not be deleted if given.
	"""

	temporary_folder = tempDir or tempfile.mkdtemp()
	with cd(temporary_folder):
		yield temporary_folder

	if not tempDir and os.path.exists(temporary_folder):
		shutil.rmtree(temporary_folder)

@contextmanager
def cd(path):
	old_dir = os.getcwd()
	os.chdir(path)
	yield
	os.chdir(old_dir)
