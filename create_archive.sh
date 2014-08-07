#!/bin/bash

destdir=$1
cwd=$(pwd)
dir=$(dirname ${cwd}/$(dirname $0))
[ "$destdir" = "" ] && destdir=$cwd

cd $dir

packagename="opsiclientd"
version=$(grep '^__version__' src/ocdlib/__init__.py| head -n1 | cut -d'=' -f2 | sed s"/\s*'//g")
tmpdir=/tmp/${packagename}-${version}

test -e $tmpdir && rm -rf $tmpdir
mkdir $tmpdir
cp -r static_html ${tmpdir}/
mkdir ${tmpdir}/src
cp -r src/gettext src/ocdlib src/windows src/setup.py ${tmpdir}/src

find ${tmpdir} -iname "*.pyc"   -exec rm "{}" \;
find ${tmpdir} -iname "*.marks" -exec rm "{}" \;
find ${tmpdir} -iname "*~"      -exec rm "{}" \;
find ${tmpdir} -iname "*.svn"   -exec rm -rf "{}" \; 2>/dev/null
find ${tmpdir} -iname ".git"   -exec rm -rf "{}" \; 2>/dev/null
find ${tmpdir} -iname ".gitignore"   -exec rm -rf "{}" \; 2>/dev/null

cd ${tmpdir}/..
tar cjvf ${destdir}/${packagename}-${version}.tar.bz2 ${packagename}-${version}
rm -rf $tmpdir
echo "============================================================================================="
echo "source archive: ${destdir}/${packagename}_${version}.tar.bz2"
echo "============================================================================================="
cd $cwd

