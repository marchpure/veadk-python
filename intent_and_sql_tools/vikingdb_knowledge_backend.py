import json
import os

import requests
from volcengine.auth.SignerV4 import SignerV4
from volcengine.base.Request import Request
from volcengine.Credentials import Credentials


def _build_vikingdb_knowledgebase_request(
    path: str,
    volcengine_access_key: str,
    volcengine_secret_key: str,
    session_token: str = "",
    method: str = "POST",
    region: str = "cn-beijing",
    params=None,
    data=None,
    doseq=0,
) -> Request:
    if params:
        for key in params:
            if isinstance(params[key], (int, float, bool)):
                params[key] = str(params[key])
            elif isinstance(params[key], list) and not doseq:
                params[key] = ",".join(params[key])

    request = Request()
    request.set_shema("https")
    request.set_method(method)
    request.set_connection_timeout(10)
    request.set_socket_timeout(10)
    request.set_headers(
        {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
    )

    if params:
        request.set_query(params)

    request.set_path(path)

    if data is not None:
        request.set_body(json.dumps(data))

    credentials = Credentials(
        volcengine_access_key, volcengine_secret_key, "air", region, session_token
    )
    SignerV4.sign(request, credentials)
    return request


class VikingDBKnowledgeBackend:
    def __init__(self, index: str):
        self.index = index
        self.volcengine_access_key = os.getenv("VOLCENGINE_ACCESS_KEY", "")
        self.volcengine_secret_key = os.getenv("VOLCENGINE_SECRET_KEY", "")
        self.session_token = os.getenv("VOLCENGINE_SESSION_TOKEN", "")
        self.volcengine_project = os.getenv("DATABASE_VIKING_PROJECT", "default")
        self.region = os.getenv("DATABASE_VIKING_REGION", "cn-beijing")
        base_url = os.getenv(
            "DATABASE_VIKING_BASE_URL",
            "https://api-knowledgebase.mlp.cn-beijing.volces.com",
        )
        if base_url.startswith("http://") or base_url.startswith("https://"):
            self.base_url = base_url
        else:
            self.base_url = f"https://{base_url}"

    def _do_request(self, body: dict, path: str, method: str = "POST") -> dict:
        full_path = f"{self.base_url}{path}"
        request = _build_vikingdb_knowledgebase_request(
            path=path,
            volcengine_access_key=self.volcengine_access_key,
            volcengine_secret_key=self.volcengine_secret_key,
            session_token=self.session_token,
            method=method,
            region=self.region,
            data=body,
        )
        response = requests.request(
            method=method,
            url=full_path,
            headers=request.headers,
            data=request.body,
        )
        return response.json()
