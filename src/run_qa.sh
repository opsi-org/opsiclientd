#! /bin/sh

TARGETS="ocdlib/ ocdlibnonfree/ scripts/opsiclientd windows/helpers/opsiclientd_rpc/opsiclientd_rpc.py windows/helpers/action_processor_starter/action_processor_starter.py linux/notifier.py"

pylint --rcfile=../pylintrc $TARGETS > pylint.txt || echo 'pylint did not finish with return code 0'
flake8 --exit-zero --ignore=W191 $TARGETS > pep8.txt
nosetests --with-xunit --with-xcoverage --cover-package=ocdlib --cover-package=ocdlibnonfree tests/ || echo 'nosetests did not finish with return code 0'
