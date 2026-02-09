#!/bin/bash
###
 # @Author: haoxingjun
 # @Date: 2026-02-05 18:20:23
 # @Email: haoxingjun@bytedance.com
 # @LastEditors: haoxingjun
 # @LastEditTime: 2026-02-09 18:25:01
 # @Description: file information
 # @Company: ByteDance
### 

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "${SCRIPT_DIR}/python" ]; then
  export PYTHONPATH="${PYTHONPATH}:${SCRIPT_DIR}/python"
else
  pip install -r requirements.txt
  export PYTHONPATH="${PYTHONPATH}:$(cd "${SCRIPT_DIR}/../../.." && pwd)"
fi

# 启动服务，监听端口
python3 -m uvicorn vefaas_app:app --host 0.0.0.0 --port "${PORT:-8000}"
