from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from shutil import copyfile
from typing import TYPE_CHECKING
from uuid import UUID

import aioboto3
import cv2
import sentry_sdk
import uuid7
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from types_aiobotocore_s3 import S3Client

from worker.api_client import generate_es512_key_pair, init_api_client
from worker.auth import create_async_creator, is_database_local
from worker.bastion import BastionConfig, BastionSession
from worker.consts import WORKER_HEARTBEAT_INTERVAL_SECONDS
from worker.generated.models import Worker
from worker.matcher import DocumentMatcher, warmup_matcher
from worker.ssm import load_ssm_parameters
from worker.telemetry import init_telemetry

from .health import HEALTH_PORT, start_health_server
from .paths import ASSETS_DIR, IMAGES_DIR, init_storage_dirs
from .worker import ScanWorker
from .worker.spot import SpotInterruptionMonitor

# Warmup image paths (used for GPU model initialization)
WARMUP_IMAGE_A = ASSETS_DIR / "warmup" / "sample_scan.jpg"
WARMUP_IMAGE_B = ASSETS_DIR / "warmup" / "sample_template.png"

# Application directory (for reading S3 config from wheels/)
APP_DIR = "/opt/shelfalign-worker"


async def upload_inductor_cache_if_needed() -> None:
    """Upload inductor cache to S3 if it was just compiled (not downloaded).

    Called after successful warmup to share compiled kernels with future deployments.
    Runs as a background task to avoid blocking worker startup.
    """
    logger = logging.getLogger(__name__)

    cache_dir = os.environ.get("TORCHINDUCTOR_CACHE_DIR")
    if not cache_dir:
        return

    cache_path = Path(cache_dir)
    downloaded_marker = cache_path / ".downloaded"
    cache_key_file = cache_path / ".cache-key"

    # Skip if cache was downloaded (not freshly compiled)
    if downloaded_marker.exists():
        logger.info("Inductor cache was downloaded, skipping upload")
        return

    if not cache_key_file.exists():
        logger.warning("No .cache-key file found, skipping inductor cache upload")
        return

    cache_key = cache_key_file.read_text().strip()

    # Get S3 bucket/prefix from wheels config
    s3_bucket_file = Path(APP_DIR) / "wheels" / ".s3-bucket"
    s3_prefix_file = Path(APP_DIR) / "wheels" / ".s3-prefix"

    if not s3_bucket_file.exists():
        logger.warning("No S3 bucket config found, skipping inductor cache upload")
        return

    s3_bucket = s3_bucket_file.read_text().strip()
    s3_prefix = s3_prefix_file.read_text().strip() if s3_prefix_file.exists() else ""

    if s3_prefix:
        s3_path = f"s3://{s3_bucket}/{s3_prefix}/inductor-cache/{cache_key}.tar.gz"
    else:
        s3_path = f"s3://{s3_bucket}/inductor-cache/{cache_key}.tar.gz"

    try:
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as f:
            tarball = f.name

        # Create tarball (exclude marker files)
        tar_proc = await asyncio.create_subprocess_exec(
            "tar",
            "-czf",
            tarball,
            "--exclude=.downloaded",
            "--exclude=.cache-key",
            "-C",
            cache_dir,
            ".",
        )
        await tar_proc.wait()
        if tar_proc.returncode != 0:
            raise RuntimeError(f"tar failed with return code {tar_proc.returncode}")

        # Upload to S3
        s3_proc = await asyncio.create_subprocess_exec("aws", "s3", "cp", tarball, s3_path)
        await s3_proc.wait()
        if s3_proc.returncode != 0:
            raise RuntimeError(f"aws s3 cp failed with return code {s3_proc.returncode}")

        logger.info(f"Uploaded inductor cache to {s3_path}")
        print(f"[Inductor] Cache uploaded to {s3_path}")

        os.unlink(tarball)
    except Exception as e:
        logger.error(f"Failed to upload inductor cache: {e}")
        print(f"[Inductor] Cache upload failed: {e}")


async def start_heartbeat(session_factory: async_sessionmaker, worker_id: UUID) -> None:
    """Background task that updates the Worker heartbeat_at every 3 seconds."""
    while True:
        try:
            async with session_factory() as session:
                await session.execute(text('UPDATE "Worker" SET "heartbeatAt" = NOW() WHERE id = :worker_id'), {"worker_id": worker_id})
                await session.commit()
        except Exception as e:
            print(f"[Heartbeat] Failed to update heartbeat: {e}")
        await asyncio.sleep(WORKER_HEARTBEAT_INTERVAL_SECONDS)


async def create_database_engine(database_url: str, bastion: BastionSession | None = None):
    if is_database_local():
        return create_async_engine(database_url, pool_pre_ping=True)

    async_creator = await create_async_creator(database_url, bastion=bastion)
    return create_async_engine(database_url, pool_pre_ping=True, async_creator=async_creator)


async def start_bastion_session_if_enabled(database_url: str) -> BastionSession | None:
    """Start a bastion lease session if BASTION_ENABLED is truthy.

    Returns the active session or None when disabled. Caller is responsible
    for closing the returned session via ``__aexit__``.
    """
    if not BastionConfig.is_enabled():
        return None

    from sqlalchemy.engine.url import make_url

    url = make_url(database_url)
    if url.host is None or url.username is None:
        raise ValueError("DATABASE_URL must include host and username for bastion mode")

    config = await BastionConfig.from_env(
        rds_endpoint=url.host,
        rds_port=url.port or 5432,
        db_user=url.username,
    )
    session = BastionSession(config)
    await session.__aenter__()
    print(f"[Bastion] Lease opened via {config.broker_url} → {session.lease.bastion_ip}:{session.lease.bastion_port}")
    return session


async def process_local_image(client: S3Client, worker: ScanWorker, image_path: str):
    print()
    print(f"Processing local image: {image_path}")
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"Failed to read image from {image_path}")
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    dirname = os.path.dirname(image_path)
    filename = os.path.basename(image_path)

    job_id, request_id = uuid7.create(), uuid7.create()

    # Create processor (default to version 1.0)
    version = 1.0
    processor = worker._create_processor(version)

    result = await processor.process(image, job_id, request_id, {})
    copyfile(os.path.join(IMAGES_DIR, f"{job_id}_annotated.png"), f"{dirname}/annotated_{filename}")
    copyfile(os.path.join(IMAGES_DIR, f"{job_id}_annotated_cropped.png"), f"{dirname}/annotated_cropped_{filename}")
    copyfile(os.path.join(IMAGES_DIR, f"{job_id}_thresh.png"), f"{dirname}/thresh_{filename}")
    copyfile(os.path.join(IMAGES_DIR, f"{job_id}_close.png"), f"{dirname}/thresh_close_{filename}")
    print("Student Info", result["student_info_results"])
    print("Problem Results", result["problem_results"])


async def main():
    await load_ssm_parameters()  # Load from SSM if SSM_PARAMETER_PATH is set
    load_dotenv()  # Then load from .env (won't override SSM values)

    # Sentry handles errors + logs. Performance is sampled at 1% only so
    # errors still carry trace context without every scan becoming a
    # billed transaction (at 1.0 it would). Full-fidelity distributed
    # tracing flows separately through our own OTel TracerProvider to the
    # local collector (see worker.telemetry / OTEL_EXPORTER_OTLP_ENDPOINT).
    sentry_sdk.init(
        dsn=os.getenv("SENTRY_DSN"),
        send_default_pii=True,
        enable_logs=True,
        traces_sample_rate=0.01,
    )

    init_storage_dirs()

    BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
    if BUCKET_NAME is None:
        raise ValueError("S3_BUCKET_NAME environment variable is not set")

    DATABASE_URL = os.getenv("DATABASE_URL")
    if DATABASE_URL is None:
        raise ValueError("DATABASE_URL environment variable is not set")

    # Convert postgres:// to postgresql+psycopg:// for async support
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

    bastion_session = await start_bastion_session_if_enabled(DATABASE_URL)
    try:
        engine = await create_database_engine(DATABASE_URL, bastion=bastion_session)
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    
        # Register worker in database
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
    
        hostname = socket.gethostname()
        try:
            ip_address = socket.gethostbyname(hostname)
        except socket.gaierror:
            ip_address = "127.0.0.1"
    
        worker_id = uuid7.create()
        private_key, public_key = generate_es512_key_pair()
    
        async with session_factory() as db_session:
            worker_record = Worker(
                id=worker_id,
                hostname=hostname,
                ip_address=ip_address,
                public_key=public_key,
                registered_at=datetime.now(),
                heartbeat_at=datetime.now(),
            )
            db_session.add(worker_record)
            await db_session.commit()
    
        print(f"[Worker] Registered with ID: {worker_id}")

        # Initialize OTel metrics exporter (no-op when OTEL_EXPORTER_OTLP_ENDPOINT is unset)
        init_telemetry(worker_id=str(worker_id), hostname=hostname)

        # Initialize API client with worker ID and private key for JWT auth
        init_api_client(os.getenv("API_BASE_URL"), worker_id, private_key)
    
        session = aioboto3.Session()
        async with session.client("s3") as client:
            worker = ScanWorker(client=client, bucket_name=BUCKET_NAME, engine=engine, worker_id=worker_id)
    
            # Register signal handlers for graceful shutdown (ECS sends SIGTERM)
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, worker.request_shutdown)
    
            # EC2 Spot interruption monitor (only starts if on EC2)
            spot_monitor = SpotInterruptionMonitor(on_interruption=worker.request_shutdown)
            spot_task: asyncio.Task | None = None
            if await SpotInterruptionMonitor.is_ec2_instance():
                spot_task = asyncio.create_task(spot_monitor.start())
                print("[Spot] Interruption monitor started")
            else:
                print("[Spot] Not running on EC2, monitor disabled")

            # If bastion keepalive dies permanently, the held lease is stale and
            # every future DB connection will fail. Treat it as a fatal event and
            # kick the graceful-shutdown path so the orchestrator restarts us.
            bastion_watchdog_task: asyncio.Task | None = None
            if bastion_session is not None:
                async def _watch_bastion_keepalive(session: BastionSession) -> None:
                    await session.keepalive_lost.wait()
                    print("[Bastion] Keepalive permanently lost; requesting shutdown")
                    worker.request_shutdown()

                bastion_watchdog_task = asyncio.create_task(_watch_bastion_keepalive(bastion_session))
    
            # Start health check server as a background task
            health_task = asyncio.create_task(start_health_server(worker))
            print(f"[Health] Server started on port {HEALTH_PORT}")
    
            # Start heartbeat background task
            heartbeat_task = asyncio.create_task(start_heartbeat(session_factory, worker_id))
            print(f"[Heartbeat] Started (interval: {WORKER_HEARTBEAT_INTERVAL_SECONDS}s)")
    
            # Initialize RoMaV2 matcher after health server startup so deployment validation can connect.
            print(f"[Matcher] RoMaV2 device: {DocumentMatcher.get_device()}")
            matcher = DocumentMatcher.get_instance()
            if os.path.exists(WARMUP_IMAGE_A) and os.path.exists(WARMUP_IMAGE_B):
                print("[Matcher] Warming up RoMaV2 model...")
                if not warmup_matcher(str(WARMUP_IMAGE_A), str(WARMUP_IMAGE_B)):
                    raise RuntimeError("RoMaV2 warmup failed")
                print("[Matcher] Warmup completed successfully")
                asyncio.create_task(upload_inductor_cache_if_needed())
            else:
                print("[Matcher] Warmup images not found, initializing RoMaV2 without warmup")
                if not matcher.initialize():
                    raise RuntimeError("RoMaV2 initialization failed")
    
            # Mark worker as ready after warmup
            worker.set_ready(True)
            print("[Worker] Ready to process jobs")
    
            if len(sys.argv) == 3 and sys.argv[1] == "local":
                image_path = sys.argv[2]
    
                if not os.path.exists(image_path):
                    raise ValueError(f"Image path does not exist: {image_path}")
    
                if os.path.isdir(image_path):
                    for filename in sorted(os.listdir(image_path)):
                        file_path = os.path.join(image_path, filename)
                        if not os.path.isfile(file_path):
                            continue
    
                        if filename.startswith("annotated_") or filename.startswith("thresh_"):
                            continue
    
                        try:
                            await process_local_image(client, worker, file_path)
                        except Exception as e:
                            print(f"Failed to process {file_path}: {e}")
    
            else:
                await worker.start()
    
            if spot_task:
                spot_task.cancel()
            if bastion_watchdog_task:
                bastion_watchdog_task.cancel()
            heartbeat_task.cancel()
            health_task.cancel()
    finally:
        if bastion_session is not None:
            await bastion_session.__aexit__(None, None, None)


if __name__ == "__main__":
    asyncio.run(main())
