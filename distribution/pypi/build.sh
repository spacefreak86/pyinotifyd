#!/bin/bash
set -e
script_dir="$(dirname "$(readlink -f -- "$BASH_SOURCE")")"
pkg_dir="$(realpath "${script_dir}/../..")"
setup="$(which python) setup.py"
cd "${pkg_dir}"
${setup} clean
${setup} sdist bdist_wheel
