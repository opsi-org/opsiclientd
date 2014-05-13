#! /bin/sh

TARGETS="ocdlib/ ocdlibnonfree/ scripts/opsiclientd windows/helpers/opsiclientd_rpc/opsiclientd_rpc.py windows/helpers/action_processor_starter/action_processor_starter.py"

pylint --rcfile=../pylintrc $TARGETS > pylint.txt || echo 'pylint did not finish with return code 0'
flake8 --ignore=W191 $TARGETS > pep8.txt || echo 'pep8 did not finish with return code 0'
nosetests --with-xunit --with-xcoverage --cover-package=ocdlib --cover-package=ocdlibnonfree tests/ || echo 'nosetests did not finish with return code 0'
