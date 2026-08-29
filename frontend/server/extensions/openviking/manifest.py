"""Public metadata for the OpenViking Knowledge Source extension."""

PROVIDER = "openviking"
CAPABILITIES = ("workspace", "context", "resource-picker")


def extension_manifest() -> dict[str, object]:
    return {"provider": PROVIDER, "capabilities": list(CAPABILITIES)}
