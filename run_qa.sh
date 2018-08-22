#! /bin/sh

TARGETS="ocdlib/ ocdlibnonfree/ scripts/opsiclientd windows/helpers/opsiclientd_rpc/opsiclientd_rpc.py windows/helpers/action_processor_starter/action_processor_starter.py windows/helpers/opsiclientd_shutdown_starter/opsiclientd_shutdown_starter.py linux/notifier.py linux/opsiclientd_rpc.py"

pylint --rcfile=.pylintrc $TARGETS > pylint.txt || echo 'pylint did not finish with return code 0'
flake8 --exit-zero --ignore=W191 $TARGETS > pep8.txt
py.test --junitxml=testreport.xml --cov ocdlib --cov ocdlibnonfree --cov-report xml --quiet tests/
