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


def _resolve_ids(config: Config, args: list[str]) -> list[int]:
    """Resolve target list from CLI args → config.targetid → available in input_dir."""
    # CLI override
    for arg in args:
        if arg == "--all":
            tids = list_targets(config.input_dir)
            if not tids:
                raise SystemExit(f"No targets found in {config.input_dir}")
            return tids
        try:
            return [int(arg)]
        except ValueError:
            pass

    # .env
    env_val = config.targetid.strip()
    if not env_val:
        tids = list_targets(config.input_dir)
        print(f"Usage: python scripts/run_pipeline.py [<targetid> | --all]")
        print(f"  Or set TARGETID in .env (single, comma-list, or 'all')")
        print(f"  INPUT_DIR:  {config.input_dir}")
        print(f"  OUTPUT_DIR: {config.output_dir}")
        print(f"  Available:  {tids}")
        raise SystemExit(1)

    if env_val.lower() == "all":
        tids = list_targets(config.input_dir)
        if not tids:
            raise SystemExit(f"No targets found in {config.input_dir}")
        return tids

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
            ti = load_target(config.input_dir, tid)
            await runner.run(ti)
        except Exception as e:
            print(f"  TARGETID {tid} FAILED: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
