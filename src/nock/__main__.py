import sys

from nock.utils import cache_bytecode

# A hook runs on every tool call, so it skips loading the rest of the CLI.
if sys.argv[1:2] == ["hook"]:
    from nock.hooks import main
else:
    from nock.cli import main

try:
    main()
finally:
    cache_bytecode()
