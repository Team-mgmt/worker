import os
from typing import Optional

import aioboto3
import psycopg
from sqlalchemy.engine.url import make_url

from worker.bastion import BastionSession
from worker.ssm import get_region_from_imds


def is_database_local() -> bool:
    return os.getenv("DATABASE_LOCAL", "false").lower() == "true"


async def create_async_creator(
    database_url: str,
    region: Optional[str] = None,
    session: Optional[aioboto3.Session] = None,
    bastion: Optional[BastionSession] = None,
):
    url = make_url(database_url)
    host = url.host
    port = url.port or 5432
    user = url.username
    dbname = url.database

    if host is None or user is None or dbname is None:
        raise ValueError("Database URL must include host, username, and database name")

    aws_session = session if session is not None else aioboto3.Session()
    if region is None and bastion is not None:
        region = bastion.config.region
    region = region or aws_session.region_name or await get_region_from_imds()

    async def async_creator():
        async with aws_session.client("rds", region_name=region) as rds:
            token = await rds.generate_db_auth_token(
                DBHostname=host,
                Port=port,
                DBUsername=user,
                Region=region,
            )

        # When a bastion lease is active, route the TCP path through the bastion
        # EIP and leased port while preserving the real RDS endpoint for TLS
        # verification and IAM token scope (spec §12).
        if bastion is not None:
            lease = bastion.lease
            return await psycopg.AsyncConnection.connect(
                host=host,
                hostaddr=lease.bastion_ip,
                port=lease.bastion_port,
                user=user,
                password=token,
                dbname=dbname,
                sslmode="verify-full",
                sslrootcert="/etc/ssl/certs/ca-certificates.crt",
            )

        return await psycopg.AsyncConnection.connect(
            host=host,
            port=port,
            user=user,
            password=token,
            dbname=dbname,
            sslmode="verify-full",
            sslrootcert="/etc/ssl/certs/ca-certificates.crt",
        )

    return async_creator
