'''
Author: haoxingjun
Date: 2026-02-09 13:32:09
Email: haoxingjun@bytedance.com
LastEditors: haoxingjun
LastEditTime: 2026-02-09 18:36:03
Description: file information
Company: ByteDance
'''
import os
from pathlib import Path
import shutil
import subprocess
import tos

# Configuration
ak = os.getenv("VOLCENGINE_ACCESS_KEY")
sk = os.getenv("VOLCENGINE_SECRET_KEY")
endpoint = "tos-cn-beijing.volces.com"
region = "cn-beijing"
bucket_name = "emr-serverless-sdk"
object_key = "intent-api/deploy.zip"
file_path = "deploy.zip"

repo_root = Path(__file__).resolve().parent
source_dir = repo_root / "intent_and_sql_tools"
deploy_pkg_dir = repo_root / "deploy_pkg"
deploy_python_dir = deploy_pkg_dir / "python" / "intent_and_sql_tools"
entry_deploy_dir = source_dir / "entrypoints" / "deploy_pkg"
entry_run = entry_deploy_dir / "run.sh"
entry_app = entry_deploy_dir / "vefaas_app.py"
entry_requirements = entry_deploy_dir / "requirements.txt"

if not ak or not sk:
    print("Error: VOLCENGINE_ACCESS_KEY or VOLCENGINE_SECRET_KEY not found in environment.")
    exit(1)

python_root = deploy_pkg_dir / "python"
if python_root.exists():
    shutil.rmtree(python_root)
deploy_python_dir.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(source_dir, deploy_python_dir)

print(f"Installing dependencies from {entry_requirements} to {deploy_python_dir.parent}...")
subprocess.run(
    [
        "pip3",
        "install",
        "-r",
        str(entry_requirements),
        "-t",
        str(deploy_python_dir.parent),
        "--platform", "manylinux2014_x86_64",
        "--only-binary=:all:",
        "--python-version", "3.12",
    ],
    check=True,
)

deploy_pkg_dir.mkdir(parents=True, exist_ok=True)
if entry_run.exists():
    shutil.copy2(entry_run, deploy_pkg_dir / "run.sh")
    os.chmod(deploy_pkg_dir / "run.sh", 0o755)
if entry_app.exists():
    shutil.copy2(entry_app, deploy_pkg_dir / "vefaas_app.py")
if entry_requirements.exists():
    shutil.copy2(entry_requirements, deploy_pkg_dir / "requirements.txt")

deploy_zip_path = repo_root / file_path
if deploy_zip_path.exists():
    deploy_zip_path.unlink()
root_intent_pkg = deploy_pkg_dir / "intent_and_sql_tools"
if root_intent_pkg.exists():
    shutil.rmtree(root_intent_pkg)
subprocess.run(
    [
        "zip",
        "-r",
        str(deploy_zip_path),
        ".",
        "-x",
        "deploy.zip",
        "intent_and_sql_tools/*",
    ],
    cwd=str(deploy_pkg_dir),
    check=True,
)

print(f"Initializing TOS client with endpoint: {endpoint}, region: {region}")
client = tos.TosClientV2(ak, sk, endpoint, region)

try:
    print(f"Uploading {file_path} to {bucket_name}/{object_key}...")
    with open(file_path, 'rb') as f:
        # Use multipart upload for large files if simple put fails, but let's try simple put with longer timeout first
        client.put_object(bucket_name, object_key, content=f)
    print("Upload successful!")
except Exception as e:
    print(f"Upload failed: {e}")
    # Try creating bucket just in case (though unlikely needed for this specific path)
    # try:
    #     client.create_bucket(bucket_name)
    #     client.put_object(bucket_name, object_key, content=open(file_path, 'rb'))
    #     print("Upload successful after creating bucket!")
    # except Exception as e2:
    #     print(f"Retry failed: {e2}")
    exit(1)
