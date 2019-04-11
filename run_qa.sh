#! /bin/sh

TARGETS="src/ocdlib/ src/ocdlibnonfree/ src/scripts/opsiclientd"
if [ -e "src/linux/notifier.py" ]; then
	TARGETS="$TARGETS src/linux/notifier.py"
fi
if [ -e "src/linux/opsiclientd_rpc.py" ]; then
	TARGETS="$TARGETS src/linux/opsiclientd_rpc.py"
fi
if [ -e "src/windows/helpers/opsiclientd_rpc/opsiclientd_rpc.py" ]; then
	TARGETS="$TARGETS src/windows/helpers/opsiclientd_rpc/opsiclientd_rpc.py"
fi
if [ -e "src/windows/helpers/opsiclientd_shutdown_starter/opsiclientd_shutdown_starter.py" ]; then
	TARGETS="$TARGETS src/windows/helpers/opsiclientd_shutdown_starter/opsiclientd_shutdown_starter.py"
fi
if [ -e "src/windows/helpers/action_processor_starter/action_processor_starter.py" ]; then
	TARGETS="$TARGETS src/windows/helpers/action_processor_starter/action_processor_starter.py"
fi

py.test --junitxml=testreport.xml --cov ocdlib --cov ocdlibnonfree --cov-report xml --quiet src/tests/

pylint --rcfile=.pylintrc $TARGETS > pylint.txt || echo 'pylint did not finish with return code 0'
flake8 --exit-zero --ignore=W191 $TARGETS > pep8.txt