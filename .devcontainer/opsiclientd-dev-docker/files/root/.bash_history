killall -9 python
uv run pylint --disable=fixme opsiclientd
uv run pytest --tb=short -o junit_family=xunit2 --junitxml=testreport.xml --cov-append --cov opsiclientd --cov-report xml -x -s -vv tests
uv run opsiclientd --config-file=tests/data/opsiclientd.conf -l5
uv run opsiclientd -l5
