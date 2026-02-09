# Deployment Guide & FAQ

This guide details the process of packaging the `intent_and_sql_tools` service for deployment to a FaaS (Function as a Service) or Linux-based serverless environment.

## Packaging for Deployment

We provide an automated script `upload_script.py` in the project root to handle the packaging process. This script is crucial because it ensures that Python dependencies are compatible with the target Linux environment, even when packaging from macOS or Windows.

### Prerequisites

- Python 3.10+
- `pip` installed
- Access to the target Object Storage (TOS) bucket.
- Environment variables for TOS access (optional, or hardcoded in script):
  - `VOLCENGINE_ACCESS_KEY`
  - `VOLCENGINE_SECRET_KEY`

### The Packaging Script (`upload_script.py`)

The script performs the following steps:
1.  **Clean Workspace**: Removes old build artifacts (`deploy_pkg/`, `deploy.zip`).
2.  **Prepare Directory Structure**: Copies source code and entry points (`run.sh`, `vefaas_app.py`) to a temporary deployment directory.
3.  **Install Dependencies (Cross-Platform)**:
    - It reads `intent_and_sql_tools/entrypoints/deploy_pkg/requirements.txt`.
    - It uses `pip install` with specific flags to download **Linux x86_64** compatible binaries (wheels), ensuring the code runs correctly on the server.
    - Flags used: `--platform manylinux2014_x86_64`, `--only-binary=:all:`, `--python-version 3.12`.
4.  **Zip**: Compresses everything into `deploy.zip`.
5.  **Upload**: Uploads the zip file to the configured TOS path.

### How to Run

1.  **Configure**: Edit `upload_script.py` to set your specific `bucket_name`, `object_key`, `endpoint`, and `region` if they differ from the defaults.
2.  **Execute**:
    ```bash
    python3 upload_script.py
    ```
3.  **Result**: A `deploy.zip` file will be generated and uploaded. You can also manually use the generated `deploy.zip` for deployment.

---

## FAQ & Troubleshooting

### Q: Why do I see `ModuleNotFoundError: No module named 'pydantic_core._pydantic_core'` after deployment?

**Cause:**
This error occurs when the `pydantic-core` library (a dependency of `pydantic`) is installed on a non-Linux machine (like macOS M1/M2), resulting in a binary file that is incompatible with the Linux environment used by FaaS.

**Solution:**
Our `upload_script.py` handles this by explicitly telling `pip` to download the Linux version:
```python
subprocess.run([
    "pip3", "install", 
    "--platform", "manylinux2014_x86_64",  # Force Linux platform
    "--only-binary=:all:",                # Prefer binaries
    ...
])
```
**Make sure you use the `upload_script.py` to package your application, rather than manually zipping your local site-packages.**

### Q: Why did the installation fail with `volcengine==1.0.178`?

**Cause:**
Some specific versions of libraries might not have pre-built wheels for the `manylinux2014_x86_64` platform on PyPI. When we enforce binary-only installation for Linux, pip will fail if it can't find a matching wheel.

**Solution:**
Upgrade the library version. In our case, upgrading to `volcengine==1.0.214` (or newer) resolved the issue as it provides the necessary Linux wheels. Always check PyPI for available files for the specific platform you are targeting.

### Q: My deployment is missing the `run.sh` file.

**Cause:**
The `run.sh` script must be at the root of the zip file for the FaaS runtime to execute it.

**Solution:**
The `upload_script.py` ensures this by copying `intent_and_sql_tools/entrypoints/deploy_pkg/run.sh` to the root of the package before zipping. Ensure this file exists in your source tree.

### Q: How do I add new dependencies?

**Step:**
1.  Add the package name and version to `intent_and_sql_tools/entrypoints/deploy_pkg/requirements.txt`.
2.  Re-run `python3 upload_script.py`.
