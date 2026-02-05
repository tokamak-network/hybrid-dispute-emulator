"""Cost estimation via OP Succinct cost-estimator."""

import asyncio
import re
import os
from typing import AsyncGenerator, Optional, List


def parse_stdout_table(output: str) -> Optional[dict]:
    """
    Parse cost-estimator stdout table output.

    Format:
    | Metric                         | Value                     |
    | Total Instruction Count        |               567,566,494 |
    """
    lines = output.split('\n')

    data = {}
    for line in lines:
        if '|' not in line or '---' in line or 'Metric' in line:
            continue

        parts = [p.strip() for p in line.split('|')]
        if len(parts) >= 3:
            metric = parts[1].strip()
            value = parts[2].strip().replace(',', '')

            # Map metric names to keys
            mapping = {
                'Batch Start': 'batch_start',
                'Batch End': 'batch_end',
                'Total Instruction Count': 'total_cycles',
                'Total SP1 Gas': 'total_pgu',
                'Number of Blocks': 'num_blocks',
                'Number of Transactions': 'num_txs',
                'Ethereum Gas Used': 'eth_gas',
                'Oracle Verify Cycles': 'oracle_cycles',
                'Derivation Cycles': 'derivation_cycles',
                'Block Execution Cycles': 'execution_cycles',
                'Blob Verification Cycles': 'blob_cycles',
                'Cycles per Block': 'cycles_per_block',
                'Cycles per Transaction': 'cycles_per_tx',
            }

            if metric in mapping:
                try:
                    data[mapping[metric]] = int(value)
                except ValueError:
                    pass

    if not data.get('total_pgu'):
        return None

    total_cycles = data.get('total_cycles', 0)

    def pct(val):
        return round(val / total_cycles * 100, 1) if total_cycles > 0 else 0

    return {
        "blockRange": [data.get('batch_start', 0), data.get('batch_end', 0)],
        "numBlocks": data.get('num_blocks', 0),
        "numTransactions": data.get('num_txs', 0),
        "totalCycles": total_cycles,
        "totalPgu": data.get('total_pgu', 0),
        "ethGasUsed": data.get('eth_gas', 0),
        "breakdown": {
            "blobVerification": {
                "cycles": data.get('blob_cycles', 0),
                "pct": pct(data.get('blob_cycles', 0))
            },
            "derivation": {
                "cycles": data.get('derivation_cycles', 0),
                "pct": pct(data.get('derivation_cycles', 0))
            },
            "execution": {
                "cycles": data.get('execution_cycles', 0),
                "pct": pct(data.get('execution_cycles', 0))
            },
            "oracleVerify": {
                "cycles": data.get('oracle_cycles', 0),
                "pct": pct(data.get('oracle_cycles', 0))
            }
        },
        "perBlock": {
            "avgCycles": data.get('cycles_per_block', 0),
            "avgGas": data.get('eth_gas', 0) // max(data.get('num_blocks', 1), 1)
        }
    }


async def run_cost_estimator_stream(
    block_start: int,
    block_end: int,
    op_succinct_path: str
) -> AsyncGenerator[dict, None]:
    """
    Run OP Succinct cost-estimator and stream progress.
    Uses blocking subprocess.run() to ensure completion before parsing.
    """
    import subprocess

    op_path = os.path.expanduser(op_succinct_path)

    yield {
        "event": "progress",
        "data": {
            "step": "started",
            "message": f"Running cost-estimator for blocks {block_start} → {block_end}..."
        }
    }

    yield {
        "event": "progress",
        "data": {
            "step": "info",
            "message": "This may take several minutes. Please wait..."
        }
    }

    try:
        # Blocking call - wait for completion
        result = subprocess.run(
            f"just cost-estimator --start {block_start} --end {block_end} 2>&1",
            cwd=op_path,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=600  # 10 minute timeout
        )

        output = result.stdout.decode()

        yield {
            "event": "progress",
            "data": {"step": "log", "message": f"Process finished. Output lines: {len(output.splitlines())}"}
        }

        # Debug: show ALL output lines
        for i, line in enumerate(output.splitlines()):
            yield {
                "event": "progress",
                "data": {"step": "debug", "message": f"[{i}] {line}"}
            }

        # Parse the output
        parsed = parse_stdout_table(output)

        if parsed is None:
            yield {
                "event": "error",
                "data": {"message": f"Failed to parse. Check debug output above."}
            }
            return

        yield {
            "event": "progress",
            "data": {"step": "parsed", "message": f"Parsed: PGU={parsed['totalPgu']:,}, Blocks={parsed['numBlocks']}"}
        }

        yield {
            "event": "complete",
            "data": parsed
        }

    except subprocess.TimeoutExpired:
        yield {
            "event": "error",
            "data": {"message": "cost-estimator timed out (10 min limit)"}
        }
    except FileNotFoundError:
        yield {
            "event": "error",
            "data": {"message": "just command not found. Is OP Succinct installed?"}
        }
    except Exception as e:
        yield {
            "event": "error",
            "data": {"message": f"Error: {str(e)}"}
        }


def calculate_proof_cost(
    total_pgu: int,
    bisection_depth: int = 0,
    compressed_base_fee: float = 0.2,
    compressed_pgu_price: float = 0.45,
    plonk_fee: float = 0.3,
) -> dict:
    """
    Calculate proof cost using the new cost model.

    - compressed_cost = compressed_base_fee + (bPGU * compressed_pgu_price)
    - total_cost = compressed_cost + plonk_fee
    """
    bpgu = total_pgu / 1_000_000_000

    if bisection_depth > 0:
        bpgu = bpgu / (2 ** bisection_depth)

    compressed_cost = compressed_base_fee + (bpgu * compressed_pgu_price)
    total_cost = compressed_cost + plonk_fee

    return {
        "bpgu": round(bpgu, 6),
        "compressed": round(compressed_cost, 4),
        "plonk": plonk_fee,
        "total_prove": round(total_cost, 4),
    }


def calculate_cost_scenarios(
    total_pgu: int,
    prove_price_usd: float = 0.34,
    compressed_base_fee: float = 0.2,
    compressed_pgu_price: float = 0.45,
    plonk_fee: float = 0.3,
) -> List[dict]:
    """Calculate cost scenarios for various bisection depths."""
    scenarios = []

    # Full batch (d=0)
    cost = calculate_proof_cost(total_pgu, 0, compressed_base_fee, compressed_pgu_price, plonk_fee)
    scenarios.append({
        "label": "Full Batch",
        "depth": 0,
        "bpgu": cost["bpgu"],
        "compressed": cost["compressed"],
        "plonk": cost["plonk"],
        "total_prove": cost["total_prove"],
        "usd": round(cost["total_prove"] * prove_price_usd, 4)
    })

    # Bisection depths
    for d in [5, 7, 10, 11]:
        cost = calculate_proof_cost(total_pgu, d, compressed_base_fee, compressed_pgu_price, plonk_fee)
        scenarios.append({
            "label": f"Bisect d={d}",
            "depth": d,
            "bpgu": cost["bpgu"],
            "compressed": cost["compressed"],
            "plonk": cost["plonk"],
            "total_prove": cost["total_prove"],
            "usd": round(cost["total_prove"] * prove_price_usd, 4)
        })

    return scenarios


def get_cost_model(
    total_pgu: int,
    prove_price_usd: float,
    config_cost_model: dict
) -> dict:
    """Get full cost model with scenarios."""
    compressed_base_fee = config_cost_model.get("compressed_base_fee", 0.2)
    compressed_pgu_price = config_cost_model.get("compressed_pgu_price", 0.45)
    plonk_fee = config_cost_model.get("plonk_fee", 0.3)

    scenarios = calculate_cost_scenarios(
        total_pgu=total_pgu,
        prove_price_usd=prove_price_usd,
        compressed_base_fee=compressed_base_fee,
        compressed_pgu_price=compressed_pgu_price,
        plonk_fee=plonk_fee,
    )

    return {
        "prove_price_usd": prove_price_usd,
        "compressed_base_fee": compressed_base_fee,
        "compressed_pgu_price": compressed_pgu_price,
        "plonk_fee": plonk_fee,
        "total_pgu": total_pgu,
        "scenarios": scenarios
    }
