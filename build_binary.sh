#! /bin/bash -e

# This file is part of opsiclientd.
# Copyright (C) 2013 uib GmbH <info@uib.de>

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

cd src/
python setup-cx-freeze.py build
cd build/
if [ -e opsiclientd -a -d opsiclientd ]; then
	echo "Removing old build directory."
	rm -rf opsiclientd/
fi
mv exe.* opsiclientd
cd opsiclientd
tar -czvvf ../opsiclientd.tar.gz *
echo "Build completed."
