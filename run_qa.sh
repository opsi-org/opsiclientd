#! /bin/sh -e

TARGETS="src/ocdlib/ src/ocdlibnonfree/ src/scripts/opsiclientd src/windows/helpers/opsiclientd_rpc/opsiclientd_rpc.py src/windows/helpers/action_processor_starter/action_processor_starter.py src/windows/helpers/opsiclientd_shutdown_starter/opsiclientd_shutdown_starter.py src/linux/notifier.py src/linux/opsiclientd_rpc.py"

py.test --junitxml=testreport.xml --cov ocdlib --cov ocdlibnonfree --cov-report xml --quiet src/tests/

pylint --rcfile=.pylintrc $TARGETS > pylint.txt || echo 'pylint did not finish with return code 0'
flake8 --exit-zero --ignore=W191 $TARGETS > pep8.txt