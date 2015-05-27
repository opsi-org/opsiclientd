#! /bin/bash

cd src/
python setup-cx-freeze.py build
cd build/
mv exe.* opsiclientd
tar -czvvf opsiclientd.tar.gz opsiclientd/
