#!/usr/bin/env bash

# This file is Not licensed to ASF
# SKIP LICENSE INSERTION

export PYTHON_VERSION=3.11

# shellcheck disable=SC2153
export TAG=${CIRCLE_TAG}

echo "TAG: $TAG"
# shellcheck disable=SC2153
BRANCH=${CIRCLE_BRANCH}
export BRANCH
echo "BRANCH: $BRANCH"

AIRFLOW_VERSION=$(awk '/__version__ =/{print $NF; exit}' airflow-core/src/airflow/__init__.py | tr -d \')
export AIRFLOW_VERSION
echo "Current Version is: ${AIRFLOW_VERSION}"
clean_version=${AIRFLOW_VERSION//\"/}
formatted_branch=${BRANCH#v}
formatted_branch=${formatted_branch//-/.}

# If tag, check if it matches the version of this app
if [[ -n ${TAG} ]]; then
    if [[ "$TAG" != "v$clean_version" ]]; then
        info="Git Tag: $TAG does not match the version of this app: v$clean_version"
        echo "$info"
        exit 1
    elif [[ "$TAG" != *"${formatted_branch}"* ]]; then
        info="Git Tag: $TAG does not match the branch of this app: $BRANCH"
        echo "$info"
        exit 1
    fi
fi

# If branch, check if it matches the version of this app
if [[ -n ${BRANCH} ]]; then
    formatted_branch=${BRANCH#v}
    formatted_branch=${formatted_branch//-/.}
    if [[ "$BRANCH" != "main-dev" ]] && [[ ! "$AIRFLOW_VERSION" == *"$formatted_branch"* ]]; then
        info="Git Branch: $BRANCH does not match the version of this app: v$clean_version"
        echo "$info"
        exit 1
    fi
fi

# Check if the version matches the expected format of 2.8.0.dev0+astro.1
pattern="^[0-9]+\.[0-9]+\.[0-9]+(\.(dev|rc)[0-9]+)?(\+astro\.[0-9]+$|\+astronightly$)"

# Check if version does not match the pattern
if ! echo "$clean_version" | grep -qE "$pattern"; then
    info="Version: $clean_version does not match the expected format of '1.2.3+astro.4' or '1.2.3.(dev|rc)4+astro.5'"
    echo "$info"
    exit 1
fi

rm -rf dist && mkdir dist

# If the build is not a tag/release, build a dev version
if [[ -z ${TAG:=} ]]; then
    if [[ ${AIRFLOW_VERSION} == *"dev"* ]]; then
        echo "Building and releasing a DEV Package"
        echo "${AIRFLOW_VERSION}"
        git fetch --unshallow

        COMMITS_SINCE_LAST_TAG="$(git rev-list "$(git describe --abbrev=0 --tags)"..HEAD --count)"
        echo "Commits since last tag: $COMMITS_SINCE_LAST_TAG"
        sed -i -E "s/dev[0-9]+\+astro/dev${COMMITS_SINCE_LAST_TAG}\+astro/g" airflow-core/src/airflow/__init__.py

        UPDATED_AIRFLOW_VERSION=$(awk '/__version__ = /{print $NF}' airflow-core/src/airflow/__init__.py | tr -d \')
        # replace the version in pyproject.toml with the updated version using sed to search for version= 3.0.0 pattern
        sed -i -E "s/^version = .*/version = $UPDATED_AIRFLOW_VERSION/" airflow-core/pyproject.toml
        sed -i -E 's/(apache-airflow-task-sdk)<[^"]+/\1/' airflow-core/pyproject.toml
        sed -i -E "s/^version = .*/version = $UPDATED_AIRFLOW_VERSION/" pyproject.toml
        CLEAN_UPDATED_VERSION=$(echo "$UPDATED_AIRFLOW_VERSION" | sed 's/^["'\'']//;s/["'\'']$//')
        sed -i -E "s/(apache-airflow-core==)[^\"]+/\1$CLEAN_UPDATED_VERSION/" pyproject.toml
        sed -i -E 's/(apache-airflow-task-sdk)<[^"]+/\1/'  pyproject.toml

        export UPDATED_AIRFLOW_VERSION
        echo "Updated Airflow Version: $UPDATED_AIRFLOW_VERSION"

        # Build Airflow meta package
        rm -rf .build && mkdir .build
        pip install uv pre-commit hatch
        hatch build -c -t sdist -t wheel
        mkdir dist/apache-airflow
        mv dist/*.tar.gz dist/apache-airflow/
        mv dist/*.whl dist/apache-airflow/

        # Build the core package
        cd airflow-core || exit
        rm -rf .build && mkdir .build
        pip install uv pre-commit hatch
        hatch build -c -t custom -t sdist -t wheel
        mkdir ../dist/apache-airflow-core
        mv dist/*.tar.gz ../dist/apache-airflow-core/
        mv dist/*.whl ../dist/apache-airflow-core/
        cd ..
    else
        echo "Version does not contain 'dev' in airflow-core/src/airflow/__init__.py"
        echo "Skipping build and release process"
        echo
        exit 1
    fi
elif [[ ${TAG:=} == *"${formatted_branch}"* ]]; then
    # replace the version in pyproject.toml with the current version
    sed -i -E "s/^version = .*/version = $AIRFLOW_VERSION/" airflow-core/pyproject.toml
    sed -i -E 's/(apache-airflow-task-sdk)<[^"]+/\1/' airflow-core/pyproject.toml
    sed -i -E "s/^version = .*/version = $AIRFLOW_VERSION/" pyproject.toml
    CLEAN_VERSION=$(echo "$AIRFLOW_VERSION" | sed 's/^["'\'']//;s/["'\'']$//')
    sed -i -E "s/(apache-airflow-core==)[^\"]+/\1$CLEAN_VERSION/" pyproject.toml
    sed -i -E 's/(apache-airflow-task-sdk)<[^"]+/\1/' pyproject.toml

    # Build Airflow meta package
    rm -rf .build && mkdir .build
    pip install uv pre-commit hatch
    hatch build -c -t sdist -t wheel
    mkdir dist/apache-airflow
    mv dist/*.tar.gz dist/apache-airflow/
    mv dist/*.whl dist/apache-airflow/

    # Build the core package
    cd airflow-core || exit
    rm -rf .build && mkdir .build
    pip install uv pre-commit hatch
    hatch build -c -t custom -t sdist -t wheel
    mkdir ../dist/apache-airflow-core
    mv dist/*.tar.gz ../dist/apache-airflow-core/
    mv dist/*.whl ../dist/apache-airflow-core/
    cd ..
fi

ls -altr dist/*/*


# Get the version of AC (Example 2.3.3.post7)
CURRENT_AC_VERSION=$(echo dist/apache-airflow-core/apache_airflow_core-*.whl | sed -E 's|.*apache_airflow_core-(.+)-py3-none-any.whl|\1|')
export CURRENT_AC_VERSION
echo "AC Version: $CURRENT_AC_VERSION"

# Get the version of Apache Airflow (Example 2.3.3)
AIRFLOW_BASE_VERSION=$(echo "$CURRENT_AC_VERSION" | sed -E 's|([0-9]+\.[0-9]+\.[0-9]+).*|\1|')
export AIRFLOW_BASE_VERSION
echo "Airflow Base Version: $AIRFLOW_BASE_VERSION"

# Store the latest version info in a separate file
# Example: 'apache-airflow/latest-2.3.3.build' contains '2.3.3.post7'
rm -rf apache-airflow-core && rm -rf apache-airflow
mkdir apache-airflow-core
mkdir apache-airflow

# Write latest dev/release versions in different files
if [[ ${AIRFLOW_VERSION} == *"astronightly"* ]]; then
    # Write latest dev/release versions in different files
    echo "Writing to latest-${AIRFLOW_BASE_VERSION}-nightly.build"
    echo "$CURRENT_AC_VERSION" > apache-airflow-core/latest-"$AIRFLOW_BASE_VERSION"-nightly.build
    exit 0
elif [[ ${AIRFLOW_VERSION} == *"dev"* ]]; then
    echo "Writing ${CURRENT_AC_VERSION} to apache-airflow-core/latest-${AIRFLOW_BASE_VERSION}-dev.build"
    echo "$CURRENT_AC_VERSION" > apache-airflow-core/latest-"$AIRFLOW_BASE_VERSION"-dev.build
    echo "Writing ${CURRENT_AC_VERSION} to apache-airflow/latest-${AIRFLOW_BASE_VERSION}.build"
    echo "$CURRENT_AC_VERSION" > apache-airflow/latest-"$AIRFLOW_BASE_VERSION"-dev.build
else
    echo "Writing ${CURRENT_AC_VERSION} to apache-airflow-core/latest-${AIRFLOW_BASE_VERSION}.build"
    echo "${CURRENT_AC_VERSION}" > apache-airflow-core/latest-"$AIRFLOW_BASE_VERSION".build
    echo "Writing ${CURRENT_AC_VERSION} to apache-airflow/latest-${AIRFLOW_BASE_VERSION}.build"
    echo "${CURRENT_AC_VERSION}" > apache-airflow/latest-"$AIRFLOW_BASE_VERSION".build
fi
