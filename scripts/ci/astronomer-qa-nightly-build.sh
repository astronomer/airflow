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

# From https://stackoverflow.com/a/39896036
# Use jq since it knows how to properly quote variables into JSON
#
# Also, if in the future we need to do this, you can serialize a
# (non-associative) Bash array with jq:
#
# for item in "${MY_ARRAY[@]}"; do
#     echo $item;
# done | jq -nR '{items: [inputs | .]}'
#
# We use Bash shell parameter expansion to guard against variables not being
# defined (these are also called "guarded references")
#
jq -n \
   --arg build_date "$DATE_STRING" \
   --arg git_ref_name "${GITHUB_REF_NAME:?You must specify GITHUB_REF_NAME}" \
   --arg git_ref_type "${GITHUB_REF_TYPE:?You must specify GITHUB_REF_TYPE}" \
   --arg git_commit_sha "${GITHUB_SHA:?You must specify GITHUB_SHA}" \
   --arg github_workflow "${GITHUB_WORKFLOW:?You must specify GITHUB_WORKFLOW}" \
   --arg github_job "${GITHUB_JOB:?You must specify GITHUB_JOB}" \
   --arg github_action "${GITHUB_ACTION:?You must specify GITHUB_ACTION}" \
   --arg github_run_number "${GITHUB_RUN_NUMER:?You must specify GITHUB_RUN_NUMBER}" \
   --arg github_runner_name "${RUNNER_NAME:?You must specify RUNNER_NAME}" \
   --arg github_runner_os "${RUNNER_OS:?You must specify RUNNER_OS}" \
   --arg python_version "$(python3 --version)" \
   --arg airflow_package_name "$AIRFLOW_PACKAGE_NAME" \
   --arg airflow_version "$UPDATED_AIRFLOW_VERSION" \
   --arg ac_package_name "$AC_PACKAGE_NAME" \
   --arg ac_version "$CURRENT_AC_VERSION" \
   '{
      "date": $build_date,
      "git": {
        "ref": {
          "name": $git_ref_name,
          "type": $git_ref_type
        },
        "commit": $git_commit_sha
      },
      "github": {
        "workflow": $github_workflow,
        "job_id": $github_job,
        "action": $github_action,
        "run_number": $github_run_number,
        "runner": {
          "name": $github_runner_name,
          "os": $github_runner_os
        }
      },
      "python": {
        "version": $python_version
      },
      "output": {
        "airflow": {
          "package": {
            "name": $airflow_package_name,
            "version": $airflow_version
          }
        }
        "astronomer_certified": {
          "package": {
            "name": $ac_package_name,
            "version": $ac_version
          }
        }
      }
    }' | tee astronomer-certified/latest-main.build.json
