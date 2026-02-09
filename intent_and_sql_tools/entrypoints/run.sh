#!/bin/bash
###
 # @Author: haoxingjun
 # @Date: 2026-02-05 14:26:52
 # @Email: haoxingjun@bytedance.com
 # @LastEditors: haoxingjun
 # @LastEditTime: 2026-02-09 16:35:39
 # @Description: file information
 # @Company: ByteDance
### 

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -d "${SCRIPT_DIR}/python" ]; then
  export PYTHONPATH="${SCRIPT_DIR}/python:${PYTHONPATH}"
else
  export PYTHONPATH="$(cd "${SCRIPT_DIR}/../.." && pwd):${PYTHONPATH}"
fi

python3 -m uvicorn vefaas_app:app --host 0.0.0.0 --port "${PORT:-8000}"
