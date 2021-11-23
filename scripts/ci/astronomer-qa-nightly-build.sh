#!/usr/bin/env bash

# This file is Not licensed to ASF
# SKIP LICENSE INSERTION

export PYTHON_VERSION=3.6

# shellcheck source=scripts/ci/libraries/_script_init.sh
. "$( dirname "${BASH_SOURCE[0]}" )/libraries/_script_init.sh"

# shellcheck disable=SC2153
export TAG=${GITHUB_REF/refs\/tags\//}
if [[ "$GITHUB_REF" != *"tags"* ]]; then
  export TAG=""
fi
echo "TAG: $TAG"
# shellcheck disable=SC2153
export BRANCH=${GITHUB_REF#refs/*/}
echo "BRANCH: $BRANCH"

echo
AIRFLOW_VERSION=$(awk '/version =/{print $NF; exit}' setup.py | tr -d \')
export AIRFLOW_VERSION
echo "Current Version is: ${AIRFLOW_VERSION}"

if [[ ${AIRFLOW_VERSION} != *"dev"* ]]; then
    echo "Version does not contain 'dev' in airflow/version.py"
    echo "Skipping build and release process"
    echo
    exit 1
fi

echo "Building and releasing a QA package"
echo
# This output can be very long, and is mostly useless
git fetch >/dev/null

DATE_STRING="$(date +%Y%m%d)"
sed -i -E "s/dev[0-9]+/dev${DATE_STRING}/g" airflow/version.py
sed -i -E "s/dev[0-9]+(\+astro)?/dev${DATE_STRING}/g" setup.py

UPDATED_AIRFLOW_VERSION=$(awk '/version = /{print $NF}' setup.py | tr -d \')
export UPDATED_AIRFLOW_VERSION
echo "Updated Airflow Version: $UPDATED_AIRFLOW_VERSION"

AIRFLOW_DIST_DIR="dist/apache-airflow"

python3 setup.py --quiet compile_assets bdist_wheel --dist-dir "$AIRFLOW_DIST_DIR"

# Get the package name
# As long as there's only one, this will grab it
AIRFLOW_PACKAGE_PATH=$(echo $AIRFLOW_DIST_DIR/apache_airflow-*.whl)
# shellcheck disable=SC2034
AIRFLOW_PACKAGE_NAME=$(basename "$AIRFLOW_PACKAGE_PATH")

ls -altr $AIRFLOW_DIST_DIR/*

AC_DIST_DIR="dist/astronomer-certified"

# Build the astronomer-certified release from the matching apache-airflow wheel file
python3 scripts/ci/astronomer-certified-setup.py bdist_wheel --dist-dir "$AC_DIST_DIR" "$AIRFLOW_PACKAGE_PATH"

ls -altr $AC_DIST_DIR/*

# Get the package name
# As long as there's only one, this will grab it
AC_PACKAGE_PATH=$(echo $AC_DIST_DIR/astronomer_certified-*.whl)
AC_PACKAGE_NAME=$(basename "$AC_PACKAGE_PATH")
# Get the version of AC (Example 1.10.7.post7)
CURRENT_AC_VERSION=$(echo "$AC_PACKAGE_NAME" | sed -E 's|.*astronomer_certified-(.+)-py3-none-any.whl|\1|')
export CURRENT_AC_VERSION
echo "AC Version: $CURRENT_AC_VERSION"

# Get the version of Apache Airflow (Example 1.10.7)
AIRFLOW_BASE_VERSION=$(echo "$CURRENT_AC_VERSION" | sed -E 's|([0-9]+\.[0-9]+\.[0-9]+).*|\1|')
export AIRFLOW_BASE_VERSION
echo "Airflow Base Version: $AIRFLOW_BASE_VERSION"

# Store the latest version info in a separate file
# Example: 'astronomer-certified/latest-1.10.7.build' contains '1.10.7.post7'
mkdir astronomer-certified
echo "${CURRENT_AC_VERSION}" > astronomer-certified/latest-main.build
