#!/bin/bash
set -e

TWINE=$(which twine)

script_dir=$(dirname "$(readlink -f -- "$BASH_SOURCE")")
pkg_dir=$(realpath "${script_dir}/../..")

cd "${pkg_dir}/dist"
ls -la
msg="Select version to distribute (cancel with CTRL+C):"
echo "${msg}"
select version in $(find . -maxdepth 1 -type f -name "pyinotifyd-*.*.*.tar.gz" -printf "%f\n" | sed "s#\.tar\.gz##g"); do
  [ -n "${version}" ] && break
  echo -e "\ninvalid choice\n\n${msg}"
done
${TWINE} upload "${version}"{.tar.gz,-*.whl}
