"""ARIA CLI — unified entry point for batch engine and real-time hub."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="aria",
        description="ARIA — Adaptive Residence Intelligence Architecture",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Batch engine commands
    subparsers.add_parser("snapshot", help="Collect current HA state snapshot")
    subparsers.add_parser("predict", help="Generate predictions from latest snapshot")
    subparsers.add_parser("full", help="Full daily pipeline: snapshot → predict → report")
    subparsers.add_parser("score", help="Score yesterday's predictions against actuals")
    subparsers.add_parser("retrain", help="Retrain ML models from accumulated data")
    subparsers.add_parser("meta-learn", help="LLM meta-learning to tune feature config")
    subparsers.add_parser("check-drift", help="Detect concept drift in predictions")
    subparsers.add_parser("correlations", help="Compute entity co-occurrence correlations")
    subparsers.add_parser("suggest-automations", help="Generate HA automation YAML via LLM")
    subparsers.add_parser("prophet", help="Train Prophet seasonal forecasters")
    subparsers.add_parser("occupancy", help="Bayesian occupancy estimation")
    subparsers.add_parser("power-profiles", help="Analyze per-outlet power consumption")

    # Sequence sub-commands
    seq_parser = subparsers.add_parser("sequences", help="Markov chain sequence analysis")
    seq_sub = seq_parser.add_subparsers(dest="seq_command")
    seq_sub.add_parser("train", help="Train Markov chain model from logbook sequences")
    seq_sub.add_parser("detect", help="Detect anomalous event sequences")

    # Intraday snapshot (used by hub subprocess)
    subparsers.add_parser("snapshot-intraday", help="Collect intraday snapshot (internal)")

    # Hub serve command
    serve_parser = subparsers.add_parser("serve", help="Start real-time hub and dashboard")
    serve_parser.add_argument("--port", type=int, default=8001, help="Port (default: 8001)")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")

    # Log sync
    subparsers.add_parser("sync-logs", help="Sync HA logbook to local JSON")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Dispatch to engine commands
    _dispatch(args)


def _dispatch(args):
    """Route CLI commands to engine or hub functions."""
    # Engine commands reuse the existing engine CLI logic
    ENGINE_COMMANDS = {
        "snapshot": "--snapshot",
        "predict": "--predict",
        "full": "--full",
        "score": "--score",
        "retrain": "--retrain",
        "meta-learn": "--meta-learn",
        "check-drift": "--check-drift",
        "correlations": "--entity-correlations",
        "suggest-automations": "--suggest-automations",
        "prophet": "--train-prophet",
        "occupancy": "--occupancy",
        "power-profiles": "--power-profiles",
        "snapshot-intraday": "--snapshot-intraday",
    }

    if args.command in ENGINE_COMMANDS:
        # Delegate to engine CLI with the old-style flag
        from aria.engine.cli import main as engine_main
        sys.argv = ["aria", ENGINE_COMMANDS[args.command]]
        engine_main()

    elif args.command == "sequences":
        if args.seq_command == "train":
            sys.argv = ["aria", "--train-sequences"]
        elif args.seq_command == "detect":
            sys.argv = ["aria", "--sequence-anomalies"]
        else:
            print("Usage: aria sequences {train|detect}")
            sys.exit(1)
        from aria.engine.cli import main as engine_main
        engine_main()

    elif args.command == "serve":
        _serve(args.host, args.port)

    elif args.command == "sync-logs":
        _sync_logs()

    else:
        print(f"Unknown command: {args.command}")
        sys.exit(1)


def _serve(host: str, port: int):
    """Start the ARIA real-time hub."""
    import asyncio
    import logging
    import os
    from pathlib import Path

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("aria.serve")

    import uvicorn
    from aria.hub.core import IntelligenceHub
    from aria.hub.api import create_api
    from aria.modules.discovery import DiscoveryModule
    from aria.modules.ml_engine import MLEngine
    from aria.modules.orchestrator import OrchestratorModule
    from aria.modules.patterns import PatternRecognition
    from aria.modules.intelligence import IntelligenceModule
    from aria.modules.activity_monitor import ActivityMonitor
    from aria.modules.shadow_engine import ShadowEngine

    async def start():
        # Setup cache
        cache_dir = Path(os.path.expanduser("~/ha-logs/intelligence/cache"))
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = str(cache_dir / "hub.db")

        logger.info("=" * 70)
        logger.info("ARIA — Adaptive Residence Intelligence Architecture")
        logger.info("=" * 70)
        logger.info(f"Cache: {cache_path}")
        logger.info(f"Server: http://{host}:{port}")
        logger.info(f"WebSocket: ws://{host}:{port}/ws")
        logger.info("=" * 70)

        hub = IntelligenceHub(cache_path)
        await hub.initialize()

        # Seed config defaults
        try:
            from aria.hub.config_defaults import seed_config_defaults
            seeded = await seed_config_defaults(hub.cache)
            if seeded:
                logger.info(f"Seeded {seeded} new config parameter(s)")
        except Exception as e:
            logger.warning(f"Config seeding failed (non-fatal): {e}")

        # HA credentials
        ha_url = os.environ.get("HA_URL")
        ha_token = os.environ.get("HA_TOKEN")
        if not ha_url or not ha_token:
            logger.error("HA_URL and HA_TOKEN environment variables required")
            await hub.shutdown()
            return

        intelligence_dir = str(cache_dir.parent)
        models_dir = os.path.join(intelligence_dir, "models")
        training_data_dir = os.path.join(intelligence_dir, "daily")

        # Register modules in order
        discovery = DiscoveryModule(hub, ha_url, ha_token)
        hub.register_module(discovery)
        await discovery.initialize()
        await discovery.schedule_periodic_discovery(interval_hours=24)
        try:
            await discovery.start_event_listener()
        except Exception as e:
            logger.warning(f"Event listener failed to start (non-fatal): {e}")

        ml_engine = MLEngine(hub, models_dir, training_data_dir)
        hub.register_module(ml_engine)
        await ml_engine.initialize()
        await ml_engine.schedule_periodic_training(interval_days=7)

        log_dir = Path(intelligence_dir)
        patterns = PatternRecognition(hub, log_dir)
        hub.register_module(patterns)
        await patterns.initialize()

        orchestrator = OrchestratorModule(hub, ha_url, ha_token)
        hub.register_module(orchestrator)
        await orchestrator.initialize()

        try:
            shadow_engine = ShadowEngine(hub)
            hub.register_module(shadow_engine)
            await shadow_engine.initialize()
        except Exception as e:
            logger.error(f"Shadow engine failed (hub continues without it): {e}")

        try:
            from aria.modules.data_quality import DataQualityModule
            data_quality = DataQualityModule(hub)
            hub.register_module(data_quality)
            await data_quality.initialize()
        except Exception as e:
            logger.warning(f"Data quality module failed (non-fatal): {e}")

        intel_mod = IntelligenceModule(hub, intelligence_dir)
        hub.register_module(intel_mod)
        try:
            await intel_mod.initialize()
            await intel_mod.schedule_refresh()
        except Exception as e:
            logger.warning(f"Intelligence module failed (non-fatal): {e}")

        try:
            activity_monitor = ActivityMonitor(hub, ha_url, ha_token)
            hub.register_module(activity_monitor)
            await activity_monitor.initialize()
        except Exception as e:
            logger.warning(f"Activity monitor failed (non-fatal): {e}")

        app = create_api(hub)

        config = uvicorn.Config(
            app, host=host, port=port,
            log_level="info", access_log=True,
        )
        server = uvicorn.Server(config)

        try:
            await server.serve()
        finally:
            if hub.is_running():
                await hub.shutdown()

    asyncio.run(start())


def _sync_logs():
    """Run ha-log-sync."""
    import subprocess
    import os
    bin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sync_script = os.path.join(bin_dir, "bin", "ha-log-sync")
    subprocess.run([sys.executable, sync_script], check=True)


if __name__ == "__main__":
    main()
