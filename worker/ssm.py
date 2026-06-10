"""Load environment variables from AWS SSM Parameter Store."""

from __future__ import annotations

import os

import aioboto3
import aiohttp

IMDS_TOKEN_URL = "http://169.254.169.254/latest/api/token"
IMDS_REGION_URL = "http://169.254.169.254/latest/meta-data/placement/region"
IMDS_TOKEN_TTL = "21600"


async def get_region_from_imds() -> str | None:
    """Fetch region from EC2 Instance Metadata Service (IMDSv2)."""
    try:
        async with aiohttp.ClientSession() as http:
            # Get IMDSv2 token
            async with http.put(
                IMDS_TOKEN_URL,
                headers={"X-aws-ec2-metadata-token-ttl-seconds": IMDS_TOKEN_TTL},
                timeout=aiohttp.ClientTimeout(total=2),
            ) as resp:
                if resp.status != 200:
                    return None
                token = await resp.text()

            # Fetch region using token
            async with http.get(
                IMDS_REGION_URL,
                headers={"X-aws-ec2-metadata-token": token},
                timeout=aiohttp.ClientTimeout(total=2),
            ) as resp:
                if resp.status != 200:
                    return None
                return await resp.text()
    except Exception:
        return None


async def load_ssm_parameters() -> None:
    """Load SSM parameters into environment variables.

    Reads parameters from the path specified in SSM_PARAMETER_PATH environment variable.
    Each parameter name (last segment of the path) becomes an environment variable.
    Optionally specify SSM_PARAMETER_REGION to override the AWS region.

    Example: /shelfalign/worker/DATABASE_URL -> DATABASE_URL env var
    """
    parameter_path = os.getenv("SSM_PARAMETER_PATH")
    if not parameter_path:
        return

    # Ensure trailing slash for path prefix
    if not parameter_path.endswith("/"):
        parameter_path += "/"

    print(f"[SSM] Loading parameters from: {parameter_path}")

    session = aioboto3.Session()
    region = os.getenv("SSM_PARAMETER_REGION") or session.region_name or await get_region_from_imds()
    async with session.client("ssm", region_name=region) as ssm:
        count = 0
        paginator = ssm.get_paginator("get_parameters_by_path")
        async for page in paginator.paginate(Path=parameter_path, WithDecryption=True):
            for param in page.get("Parameters", []):
                # Extract the parameter name (last segment of the path)
                param_name = param.get("Name")
                param_value = param.get("Value")
                if param_name and param_value is not None:
                    name = param_name.rsplit("/", 1)[-1]
                    os.environ[name] = param_value
                    count += 1

        print(f"[SSM] Loaded {count} parameters")
