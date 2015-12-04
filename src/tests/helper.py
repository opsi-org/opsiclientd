#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2015 uib GmbH
# http://www.uib.de/
# All rights reserved.

import os
import shutil
import tempfile
from contextlib import contextmanager


@contextmanager
def workInTemporaryDirectory(tempDir=None):
    """
    Creates a temporary folder to work in. Deletes the folder afterwards.

    :param tempDir: use the given dir as temporary directory. Will not \
be deleted if given.
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
