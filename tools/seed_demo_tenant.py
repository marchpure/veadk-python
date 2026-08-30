#!/usr/bin/env python3
"""Explicit W5 Demo Tenant seed entry point.

The command records no success by itself.  A production integration must pass
``--gate-module`` whose async ``gate(scenario)`` performs real
Connection Service validate/discover/lease/query or invoke and real AutoSkill
generation.  Without that gate the command fails closed.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from frontend.server.knowledge_workspace.demo import (
    DemoConfig,
    DemoSeedCoordinator,
    DemoSeedStore,
    _public_state,
)
from frontend.server.knowledge_workspace.service import Actor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--principal", required=True)
    parser.add_argument("--gate-module", required=True, help="module exposing async gate(scenario)")
    parser.add_argument("--database", default=None)
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    config = DemoConfig.from_env()
    if args.database:
        config = DemoConfig(config.enabled, config.seed_version, args.database)
    module = importlib.import_module(args.gate_module)
    gate = getattr(module, "gate", None)
    if not callable(gate):
        raise RuntimeError("gate module must expose async gate(scenario)")
    actor = Actor(args.tenant, args.workspace, args.principal)
    result = await DemoSeedCoordinator(config, DemoSeedStore(config.database)).seed(
        actor, gate=gate
    )
    print(json.dumps(_public_state(result), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run()))
    except RuntimeError as exc:
        print(f"DEMO_SEED_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(2)
