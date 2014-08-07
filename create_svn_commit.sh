#!/bin/bash

#destdir=$1

[ "$destdir" = "" ] && destdir=$cwd

packagename="opsiclientd"
version=$(grep '^__version__' src/ocdlib/__init__.py| head -n1 | cut -d'=' -f2 | sed s"/\s*'//g")
tmpdir=/tmp/${packagename}-${version}


test -e $tmpdir && rm -rf $tmpdir
mkdir $tmpdir
mkdir ${tmpdir}/src
cp -r src/gettext src/static_html src/ocdlib src/windows src/tests src/setup.py src/scripts/opsiclientd ${tmpdir}/src

#cleanup
find ${tmpdir} -iname "*.pyc"   -exec rm "{}" \;
find ${tmpdir} -iname "*.marks" -exec rm "{}" \;
find ${tmpdir} -iname "*~"      -exec rm "{}" \;
find ${tmpdir} -iname "*.svn"   -exec rm -rf "{}" \; 2>/dev/null
find ${tmpdir} -iname ".git"   -exec rm -rf "{}" \; 2>/dev/null
find ${tmpdir} -iname ".gitignore"   -exec rm -rf "{}" \; 2>/dev/null


#echo "============================================================================================="
#echo "source archive: ${destdir}/${packagename}_${version}-${release}.tar.gz"
#echo "dsc file:       ${destdir}/${packagename}_${version}-${release}.dsc"
#echo "spec file:      ${destdir}/${packagename}.spec"
#echo "============================================================================================="
#cd $cwd
