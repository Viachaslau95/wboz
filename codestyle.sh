#!/bin/bash

set -e
set -x

/Users/mac/.local/bin/poetry run black ${1:-./}
/Users/mac/.local/bin/poetry run isort ${1:-./}
/Users/mac/.local/bin/poetry run ruff check --fix ${1:-./}
