#!/usr/bin/env bash

# This file is Not licensed to ASF
# SKIP LICENSE INSERTION

export PYTHON_VERSION=3.6

# shellcheck source=scripts/ci/_script_init.sh
. "$( dirname "${BASH_SOURCE[0]}" )/_script_init.sh"

# If the build is not a tag/release, build a dev version
if [[ -z ${TRAVIS_TAG:=} ]]; then
    echo
    AIRFLOW_VERSION=$(awk '/version/{print $NF}' airflow/version.py | tr -d \')
    export AIRFLOW_VERSION
    echo "Current Version is: ${AIRFLOW_VERSION}"

    if [[ ${AIRFLOW_VERSION} == *"dev"* ]]; then
        echo "Building and releasing a DEV Package"
        echo
        git fetch --unshallow

        COMMITS_SINCE_LAST_TAG="$(git rev-list "$(git describe --abbrev=0 --tags)"..HEAD --count)"
        sed -i -E "s/dev[0-9]+/dev${COMMITS_SINCE_LAST_TAG}/g" airflow/version.py

        UPDATED_AIRFLOW_VERSION=$(awk '/version/{print $NF}' airflow/version.py | tr -d \')
        export UPDATED_AIRFLOW_VERSION
        echo "Updated Airflow Version: $UPDATED_AIRFLOW_VERSION"

        python3 setup.py --quiet verify compile_assets sdist --dist-dir dist/apache-airflow/ bdist_wheel --dist-dir dist/apache-airflow/
    else
        echo "Version does not contain 'dev' in airflow/version.py"
        echo "Skipping build and release process"
        echo
        exit 1
    fi
elif [[ ${TRAVIS_TAG:=} == "${TRAVIS_BRANCH:=}" ]]; then
    python3 setup.py --quiet verify compile_assets sdist --dist-dir dist/apache-airflow/ bdist_wheel --dist-dir dist/apache-airflow/
    # Build a point release for CA (Example 1.10.7 for apache_airflow-1!1.10.7+astro.6)
    python3 astronomer-certified-point-release-setup.py bdist_wheel --dist-dir dist/astronomer-certified dist/apache-airflow/apache_airflow-*.whl
fi

ls -altr dist/*/*

# Build the astronomer-certified release from the matching apache-airflow wheel file
python3 astronomer-certified-setup.py bdist_wheel  --dist-dir dist/astronomer-certified dist/apache-airflow/apache_airflow-*.whl
