#! /bin/bash

cd src/
python setup-cx-freeze.py build
cd build/
if [ -e opsiclientd ]; then
	echo "Removing old build directory."
	rm -rf opsiclientd/
fi
mv exe.* opsiclientd
cd opsiclientd
tar -czvvf ../opsiclientd.tar.gz *
echo "Build completed."
