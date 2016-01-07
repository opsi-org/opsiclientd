#! /bin/bash -e

# This file is part of opsiclientd.
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

currentPath=$(pwd)
if [ -e opsiclientd.tar.gz ]; then
	echo "Removing old tarfile."
	rm -f opsiclientd.tar.gz
fi
cd src/
python setup-cx-freeze.py build
cd build/
if [ -e opsiclientd -a -d opsiclientd ]; then
	echo "Removing old build directory."
	rm -rf opsiclientd/
fi
mv exe.* opsiclientd
cd opsiclientd
echo "Testing created binary..."
./opsiclientd -h
./opsiclientd -V
echo "Binary test finished"
tar -czvvf ../opsiclientd.tar.gz *
mv ../opsiclientd.tar.gz "$currentPath"
echo "Build completed."
echo "File: $currentPath/opsiclientd.tar.gz"
