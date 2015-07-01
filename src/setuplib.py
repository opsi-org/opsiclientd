#! /usr/bin/env python
# -*- coding: utf-8 -*-

# This file is part of python-opsi.
# Copyright (C) 2015 uib GmbH <info@uib.de>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Shared functionality for setup scripts.

:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

import os


def getVersion():
	localDirectory = os.path.dirname(__file__)

	opsiClientDeamonVersion = None
	fileWithVersion = os.path.join(localDirectory, 'ocdlib', '__init__.py')
	with open(fileWithVersion, 'r') as f:
		for line in f:
			if "__version__" in line:
				return line.split('=', 1)[1].strip()[1:-1]

	raise Exception("Failed to find version.")
