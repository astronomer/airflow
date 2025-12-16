#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Utilities for SSH remote job execution."""

from __future__ import annotations

import re
import secrets
import string
from dataclasses import dataclass
from typing import Literal


def _validate_env_var_name(name: str) -> None:
    """
    Validate environment variable name for security.

    :param name: Environment variable name
    :raises ValueError: If name contains dangerous characters
    """
    if not name:
        raise ValueError("Environment variable name cannot be empty")

    # Check for valid characters: alphanumeric and underscore only (POSIX-compatible)
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
        raise ValueError(
            f"Invalid environment variable name '{name}'. "
            "Only alphanumeric characters and underscores are allowed, "
            "and the name must start with a letter or underscore."
        )


def generate_job_id(
    dag_id: str,
    task_id: str,
    run_id: str,
    try_number: int,
    suffix_length: int = 8,
) -> str:
    """
    Generate a unique job ID for remote execution.

    Creates a deterministic identifier from the task context with a random suffix
    to ensure uniqueness across retries and potential race conditions.

    :param dag_id: The DAG identifier
    :param task_id: The task identifier
    :param run_id: The run identifier
    :param try_number: The attempt number
    :param suffix_length: Length of random suffix (default 8)
    :return: Sanitized job ID string
    """

    # Sanitize inputs to only allow safe characters for file/directory names
    def sanitize(value: str) -> str:
        # Replace any non-alphanumeric characters with underscores
        return re.sub(r"[^a-zA-Z0-9]", "_", value)[:50]

    sanitized_dag = sanitize(dag_id)
    sanitized_task = sanitize(task_id)
    sanitized_run = sanitize(run_id)

    # Generate random suffix
    alphabet = string.ascii_lowercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(suffix_length))

    return f"af_{sanitized_dag}_{sanitized_task}_{sanitized_run}_try{try_number}_{suffix}"


@dataclass
class RemoteJobPaths:
    """Paths for remote job artifacts on the target system."""

    job_id: str
    remote_os: Literal["posix", "windows"]
    base_dir: str | None = None

    def __post_init__(self):
        if self.base_dir is None:
            if self.remote_os == "posix":
                self.base_dir = "/tmp/airflow-ssh-jobs"
            else:
                # Use $env:TEMP which is more portable across Windows installations
                # This will be resolved at runtime on the remote host
                self.base_dir = "$env:TEMP\\airflow-ssh-jobs"

    @property
    def sep(self) -> str:
        """Path separator for the remote OS."""
        return "\\" if self.remote_os == "windows" else "/"

    @property
    def job_dir(self) -> str:
        """Directory containing all job artifacts."""
        return f"{self.base_dir}{self.sep}{self.job_id}"

    @property
    def log_file(self) -> str:
        """Path to stdout/stderr log file."""
        return f"{self.job_dir}{self.sep}stdout.log"

    @property
    def exit_code_file(self) -> str:
        """Path to exit code file (written on completion)."""
        return f"{self.job_dir}{self.sep}exit_code"

    @property
    def exit_code_tmp_file(self) -> str:
        """Temporary exit code file (for atomic write)."""
        return f"{self.job_dir}{self.sep}exit_code.tmp"

    @property
    def pid_file(self) -> str:
        """Path to PID file for the background process."""
        return f"{self.job_dir}{self.sep}pid"

    @property
    def status_file(self) -> str:
        """Path to optional status file for progress updates."""
        return f"{self.job_dir}{self.sep}status"


def build_posix_wrapper_command(
    command: str,
    paths: RemoteJobPaths,
    environment: dict[str, str] | None = None,
) -> str:
    """
    Build a POSIX shell wrapper that runs the command detached via nohup.

    The wrapper:
    - Creates the job directory
    - Starts the command in the background with nohup
    - Redirects stdout/stderr to the log file
    - Writes the exit code atomically on completion
    - Writes the PID for potential cancellation

    :param command: The command to execute
    :param paths: RemoteJobPaths instance with all paths
    :param environment: Optional environment variables to set
    :return: Shell command string to submit via SSH
    """
    # Build environment export statements
    env_exports = ""
    if environment:
        for key, value in environment.items():
            # Validate key for security
            _validate_env_var_name(key)
            # Escape single quotes in values
            escaped_value = value.replace("'", "'\"'\"'")
            env_exports += f"export {key}='{escaped_value}'\n"

    # Escape the command for embedding in the wrapper
    escaped_command = command.replace("'", "'\"'\"'")

    wrapper = f"""set -euo pipefail
job_dir='{paths.job_dir}'
log_file='{paths.log_file}'
exit_code_file='{paths.exit_code_file}'
exit_code_tmp='{paths.exit_code_tmp_file}'
pid_file='{paths.pid_file}'
status_file='{paths.status_file}'

mkdir -p "$job_dir"
: > "$log_file"

nohup bash -c '
set +e
export LOG_FILE="'"$log_file"'"
export STATUS_FILE="'"$status_file"'"
{env_exports}{escaped_command} >>"'"$log_file"'" 2>&1
ec=$?
echo -n "$ec" > "'"$exit_code_tmp"'"
mv "'"$exit_code_tmp"'" "'"$exit_code_file"'"
exit 0
' >/dev/null 2>&1 &

echo -n $! > "$pid_file"
echo "{paths.job_id}"
"""
    return wrapper


def build_windows_wrapper_command(
    command: str,
    paths: RemoteJobPaths,
    environment: dict[str, str] | None = None,
) -> str:
    """
    Build a PowerShell wrapper that runs the command detached via Start-Process.

    The wrapper:
    - Creates the job directory
    - Starts the command in a new detached PowerShell process
    - Redirects stdout/stderr to the log file
    - Writes the exit code atomically on completion
    - Writes the PID for potential cancellation

    :param command: The command to execute (PowerShell script path or command)
    :param paths: RemoteJobPaths instance with all paths
    :param environment: Optional environment variables to set
    :return: PowerShell command string to submit via SSH
    """
    # Build environment variable setup for the child process
    env_setup = ""
    if environment:
        for key, value in environment.items():
            # Validate key for security
            _validate_env_var_name(key)
            escaped_value = value.replace("'", "''")
            env_setup += f"$env:{key} = '{escaped_value}'; "

    # Escape single quotes in paths and command for PowerShell
    def ps_escape(s: str) -> str:
        return s.replace("'", "''")

    job_dir = ps_escape(paths.job_dir)
    log_file = ps_escape(paths.log_file)
    exit_code_file = ps_escape(paths.exit_code_file)
    exit_code_tmp = ps_escape(paths.exit_code_tmp_file)
    pid_file = ps_escape(paths.pid_file)
    status_file = ps_escape(paths.status_file)
    escaped_command = ps_escape(command)
    job_id = ps_escape(paths.job_id)

    # The child script that will run the user command
    child_script = f"""$ErrorActionPreference = 'Continue'
$env:LOG_FILE = '{log_file}'
$env:STATUS_FILE = '{status_file}'
{env_setup}
{escaped_command}
$ec = $LASTEXITCODE
if ($null -eq $ec) {{ $ec = 0 }}
Set-Content -NoNewline -Path '{exit_code_tmp}' -Value $ec
Move-Item -Force -Path '{exit_code_tmp}' -Destination '{exit_code_file}'
"""
    # Encode the child script for passing to powershell -EncodedCommand
    # This avoids quoting issues
    import base64

    child_script_bytes = child_script.encode("utf-16-le")
    encoded_script = base64.b64encode(child_script_bytes).decode("ascii")

    wrapper = f"""$jobDir = '{job_dir}'
New-Item -ItemType Directory -Force -Path $jobDir | Out-Null
$log = '{log_file}'
'' | Set-Content -Path $log

$p = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-NonInteractive', '-EncodedCommand', '{encoded_script}') -RedirectStandardOutput $log -RedirectStandardError $log -PassThru -WindowStyle Hidden
Set-Content -NoNewline -Path '{pid_file}' -Value $p.Id
Write-Output '{job_id}'
"""
    # Encode wrapper script for execution via SSH (ensures it runs even if default shell is cmd.exe)
    wrapper_bytes = wrapper.encode("utf-16-le")
    encoded_wrapper = base64.b64encode(wrapper_bytes).decode("ascii")

    return f"powershell.exe -NoProfile -NonInteractive -EncodedCommand {encoded_wrapper}"


def build_posix_log_tail_command(log_file: str, offset: int, max_bytes: int) -> str:
    """
    Build a POSIX command to read log bytes from offset.

    :param log_file: Path to the log file
    :param offset: Byte offset to start reading from
    :param max_bytes: Maximum bytes to read
    :return: Shell command that outputs the log chunk
    """
    return f"dd if='{log_file}' bs=1 skip={offset} count={max_bytes} 2>/dev/null || true"


def build_windows_log_tail_command(log_file: str, offset: int, max_bytes: int) -> str:
    """
    Build a PowerShell command to read log bytes from offset.

    :param log_file: Path to the log file
    :param offset: Byte offset to start reading from
    :param max_bytes: Maximum bytes to read
    :return: PowerShell command that outputs the log chunk (wrapped with powershell.exe)
    """
    import base64

    escaped_path = log_file.replace("'", "''")
    script = f"""$path = '{escaped_path}'
if (Test-Path $path) {{
  try {{
    $fs = [System.IO.File]::Open($path, 'Open', 'Read', 'ReadWrite')
    $fs.Seek({offset}, [System.IO.SeekOrigin]::Begin) | Out-Null
    $buf = New-Object byte[] {max_bytes}
    $n = $fs.Read($buf, 0, $buf.Length)
    $fs.Close()
    if ($n -gt 0) {{
      [System.Text.Encoding]::UTF8.GetString($buf, 0, $n)
    }}
  }} catch {{}}
}}"""
    script_bytes = script.encode("utf-16-le")
    encoded_script = base64.b64encode(script_bytes).decode("ascii")
    return f"powershell.exe -NoProfile -NonInteractive -EncodedCommand {encoded_script}"


def build_posix_file_size_command(file_path: str) -> str:
    """
    Build a POSIX command to get file size in bytes.

    :param file_path: Path to the file
    :return: Shell command that outputs the file size
    """
    # Try Linux stat format first, fall back to BSD/macOS format
    return f"stat -c%s '{file_path}' 2>/dev/null || stat -f%z '{file_path}' 2>/dev/null || echo 0"


def build_windows_file_size_command(file_path: str) -> str:
    """
    Build a PowerShell command to get file size in bytes.

    :param file_path: Path to the file
    :return: PowerShell command that outputs the file size (wrapped with powershell.exe)
    """
    import base64

    escaped_path = file_path.replace("'", "''")
    script = f"""$path = '{escaped_path}'
if (Test-Path $path) {{
  (Get-Item $path).Length
}} else {{
  0
}}"""
    script_bytes = script.encode("utf-16-le")
    encoded_script = base64.b64encode(script_bytes).decode("ascii")
    return f"powershell.exe -NoProfile -NonInteractive -EncodedCommand {encoded_script}"


def build_posix_completion_check_command(exit_code_file: str) -> str:
    """
    Build a POSIX command to check if job completed and get exit code.

    :param exit_code_file: Path to the exit code file
    :return: Shell command that outputs exit code if done, empty otherwise
    """
    return f"test -s '{exit_code_file}' && cat '{exit_code_file}' || true"


def build_windows_completion_check_command(exit_code_file: str) -> str:
    """
    Build a PowerShell command to check if job completed and get exit code.

    :param exit_code_file: Path to the exit code file
    :return: PowerShell command that outputs exit code if done, empty otherwise (wrapped with powershell.exe)
    """
    import base64

    escaped_path = exit_code_file.replace("'", "''")
    script = f"""$path = '{escaped_path}'
if (Test-Path $path) {{
  $txt = Get-Content -Raw -Path $path
  if ($txt -match '^[0-9]+$') {{ $txt.Trim() }}
}}"""
    script_bytes = script.encode("utf-16-le")
    encoded_script = base64.b64encode(script_bytes).decode("ascii")
    return f"powershell.exe -NoProfile -NonInteractive -EncodedCommand {encoded_script}"


def build_posix_kill_command(pid_file: str) -> str:
    """
    Build a POSIX command to kill the remote process.

    :param pid_file: Path to the PID file
    :return: Shell command to kill the process
    """
    return f"test -f '{pid_file}' && kill $(cat '{pid_file}') 2>/dev/null || true"


def build_windows_kill_command(pid_file: str) -> str:
    """
    Build a PowerShell command to kill the remote process.

    :param pid_file: Path to the PID file
    :return: PowerShell command to kill the process (wrapped with powershell.exe)
    """
    import base64

    escaped_path = pid_file.replace("'", "''")
    script = f"""$path = '{escaped_path}'
if (Test-Path $path) {{
  $pid = Get-Content $path
  Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
}}"""
    script_bytes = script.encode("utf-16-le")
    encoded_script = base64.b64encode(script_bytes).decode("ascii")
    return f"powershell.exe -NoProfile -NonInteractive -EncodedCommand {encoded_script}"


def build_posix_cleanup_command(job_dir: str) -> str:
    """
    Build a POSIX command to clean up the job directory.

    :param job_dir: Path to the job directory
    :return: Shell command to remove the directory
    """
    return f"rm -rf '{job_dir}'"


def build_windows_cleanup_command(job_dir: str) -> str:
    """
    Build a PowerShell command to clean up the job directory.

    :param job_dir: Path to the job directory
    :return: PowerShell command to remove the directory (wrapped with powershell.exe)
    """
    import base64

    escaped_path = job_dir.replace("'", "''")
    script = f"Remove-Item -Recurse -Force -Path '{escaped_path}' -ErrorAction SilentlyContinue"
    script_bytes = script.encode("utf-16-le")
    encoded_script = base64.b64encode(script_bytes).decode("ascii")
    return f"powershell.exe -NoProfile -NonInteractive -EncodedCommand {encoded_script}"


def build_posix_os_detection_command() -> str:
    """
    Build a command to detect if the remote system is POSIX-compliant.

    Returns the OS name (Linux, Darwin, FreeBSD, etc.) or UNKNOWN.
    """
    return "uname -s 2>/dev/null || echo UNKNOWN"


def build_windows_os_detection_command() -> str:
    """Build a command to detect if the remote system is Windows (wrapped with powershell.exe)."""
    import base64

    script = '$PSVersionTable.PSVersion.Major; if ($?) { "WINDOWS" }'
    script_bytes = script.encode("utf-16-le")
    encoded_script = base64.b64encode(script_bytes).decode("ascii")
    return f"powershell.exe -NoProfile -NonInteractive -EncodedCommand {encoded_script}"
