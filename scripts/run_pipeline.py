#!/usr/bin/env python
"""Run the full CataLogA pipeline.

Targets are read from ``.env`` (``TARGETID``) or the command line::

    # .env: TARGETID=39628250216924756
    python scripts/run_pipeline.py

    # .env: TARGETID=all
    python scripts/run_pipeline.py

    # CLI override
    python scripts/run_pipeline.py 39628250216924756
    python scripts/run_pipeline.py --all

``TARGETID`` supports comma-separated lists::

    TARGETID=39628250216924756,39628250216924757
"""

import asyncio
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

try:
    from dotenv import load_dotenv
    env_path = os.path.join(PROJECT_ROOT, ".env")
    load_dotenv(env_path)
    if os.path.exists(env_path):
        print(f"[dotenv] loaded {env_path}")
except ImportError:
    pass

from cataloga.core.config import Config
from cataloga.tools.inputs import load_target, list_targets
from cataloga.pipeline import PipelineRunner


def _load_target_list(config: Config) -> list[int]:
    """Read targets.txt from intermediate_dir, returning ordered list."""
    txt = os.path.join(config.intermediate_dir, "targets.txt")
    if not os.path.exists(txt):
        return list_targets(config.intermediate_dir)
    tids = []
    with open(txt) as f:
        for line in f:
            line = line.strip()
            if line:
                tids.append(int(line))
    return tids


def _resolve_ids(config: Config, args: list[str]) -> list[int]:
    """Resolve target list from CLI args → config.targetid.

    Supports:
      - ``396...`` (single TARGETID)
      - ``--all`` (all in intermediate dir)
      - ``all``, ``tail-5``, ``head-10``
      - ``[10:]``, ``[:30]``, ``[8:10,17:50]``  (Python slice syntax)
      - ``396...,396...`` (comma list)
    """
    all_tids = _load_target_list(config)
    n = len(all_tids)

    # CLI override
    for arg in args:
        if arg == "--all":
            return all_tids
        try:
            return [int(arg)]
        except ValueError:
            pass

    # .env
    env_val = config.targetid.strip()
    if not env_val:
        print(f"Usage: python scripts/run_pipeline.py [<targetid> | --all]")
        print(f"  Set TARGETID in .env: all, tail-5, head-10, [10:], [:30], [8:10,17:50]")
        print(f"  INTERMEDIATE_DIR: {config.intermediate_dir}")
        print(f"  Available: {n} targets  (first 10): {all_tids[:10]}")
        raise SystemExit(1)

    # all
    if env_val.lower() == "all":
        return all_tids

    # tail-N / head-N
    m = re.match(r'^tail-(\d+)$', env_val, re.IGNORECASE)
    if m:
        k = int(m.group(1))
        return all_tids[-k:]
    m = re.match(r'^head-(\d+)$', env_val, re.IGNORECASE)
    if m:
        k = int(m.group(1))
        return all_tids[:k]

    # Python slice syntax: [start:end], [:end], [start:], [a:b,c:d,...]
    if env_val.startswith('[') and env_val.endswith(']'):
        inner = env_val[1:-1]  # e.g. "10:" or "8:10,17:50"
        ids = []
        for segment in inner.split(','):
            segment = segment.strip()
            parts = segment.split(':')
            if len(parts) == 2:
                a = int(parts[0]) if parts[0].strip() else None
                b = int(parts[1]) if parts[1].strip() else None
                ids.extend(all_tids[a:b])
            else:
                ids.append(all_tids[int(segment)])
        return ids

    # Comma-separated integers
    ids = []
    for part in env_val.split(","):
        part = part.strip()
        if part:
            ids.append(int(part))
    if not ids:
        raise SystemExit("TARGETID is empty")
    return ids


async def main():
    config = Config()
    tids = _resolve_ids(config, sys.argv[1:])

    print(f"Targets: {tids}")
    print(f"Output:  {config.output_dir}/<targetid>/")
    runner = PipelineRunner(config)

    for tid in tids:
        try:
            ti = load_target(config.intermediate_dir, tid)
            await runner.run(ti)
        except Exception as e:
            print(f"  TARGETID {tid} FAILED: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
