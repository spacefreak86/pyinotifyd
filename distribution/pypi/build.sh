#!/bin/bash
set -e
set -x
PYTHON=$(which python)

script_dir=$(dirname "$(readlink -f -- "$BASH_SOURCE")")
pkg_dir=$(realpath "${script_dir}"/../..)

cd "${pkg_dir}"
${PYTHON} setup.py clean
${PYTHON} setup.py sdist bdist_wheel
