"""Devnet interaction via cast (Foundry)."""

import asyncio
import subprocess
import json
from typing import AsyncGenerator, Optional


def get_current_block(rpc_url: str) -> Optional[int]:
    """Get current block number from RPC."""
    try:
        result = subprocess.run(
            ["cast", "block-number", "--rpc-url", rpc_url],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
        return None
    except Exception:
        return None


def get_chain_id(rpc_url: str) -> Optional[int]:
    """Get chain ID from RPC."""
    try:
        result = subprocess.run(
            ["cast", "chain-id", "--rpc-url", rpc_url],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
        return None
    except Exception:
        return None


def get_safe_block(rpc_url: str) -> Optional[int]:
    """Get latest safe block number."""
    try:
        result = subprocess.run(
            ["cast", "block", "safe", "--rpc-url", rpc_url, "--json"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            import json
            block = json.loads(result.stdout)
            # Block number can be hex or int
            num = block.get("number")
            if isinstance(num, str) and num.startswith("0x"):
                return int(num, 16)
            return int(num)
        return None
    except Exception:
        return None


async def send_tx(
    rpc_url: str,
    private_key: str,
    to_address: str,
    value: str = "0.001ether"
) -> dict:
    """Send a single transaction using cast."""
    proc = await asyncio.create_subprocess_exec(
        "cast", "send",
        "--rpc-url", rpc_url,
        "--private-key", private_key,
        to_address,
        "--value", value,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode().strip() if stderr else "Unknown error"
        return {"success": False, "error": error_msg}

    # Parse transaction hash from output
    output = stdout.decode().strip()
    lines = output.split('\n')

    tx_hash = None
    for line in lines:
        if line.startswith('transactionHash'):
            tx_hash = line.split()[-1]
            break
        # Sometimes cast just returns the hash directly
        if line.startswith('0x') and len(line) == 66:
            tx_hash = line
            break

    return {
        "success": True,
        "tx_hash": tx_hash,
        "output": output
    }


async def send_txs_stream(
    rpc_url: str,
    private_key: str,
    account_address: str,
    count: int
) -> AsyncGenerator[dict, None]:
    """
    Send multiple transactions and yield progress updates.

    Yields SSE-compatible event dictionaries.
    """
    start_block = get_current_block(rpc_url)

    if start_block is None:
        yield {
            "event": "error",
            "data": {"message": "Cannot connect to L2 RPC", "rpc": rpc_url}
        }
        return

    yield {
        "event": "progress",
        "data": {
            "step": "started",
            "message": f"Starting TX generation (current block: {start_block})",
            "start_block": start_block
        }
    }

    tx_hashes = []
    for i in range(count):
        yield {
            "event": "progress",
            "data": {
                "step": "sending",
                "index": i + 1,
                "total": count,
                "message": f"Sending TX {i + 1}/{count}..."
            }
        }

        result = await send_tx(rpc_url, private_key, account_address)

        if not result["success"]:
            yield {
                "event": "error",
                "data": {
                    "step": "tx_failed",
                    "index": i + 1,
                    "error": result.get("error", "Unknown error")
                }
            }
            return

        tx_hashes.append(result["tx_hash"])

        yield {
            "event": "progress",
            "data": {
                "step": "tx_sent",
                "index": i + 1,
                "total": count,
                "tx_hash": result["tx_hash"]
            }
        }

        # Small delay between transactions
        await asyncio.sleep(0.5)

    # Wait for blocks to be mined
    yield {
        "event": "progress",
        "data": {"step": "waiting", "message": "Waiting for blocks to be mined..."}
    }
    await asyncio.sleep(2)

    end_block = get_current_block(rpc_url)

    yield {
        "event": "complete",
        "data": {
            "block_start": start_block,
            "block_end": end_block,
            "tx_count": count,
            "tx_hashes": tx_hashes
        }
    }
