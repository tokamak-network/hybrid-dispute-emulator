#!/usr/bin/env python3
"""
Hybrid Dispute Dashboard - FastAPI Server

Usage:
    python server.py
    # Then open http://localhost:8080
"""

import json
import yaml
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from sse_starlette.sse import EventSourceResponse

from lib.models import StatusResponse, SendTxsRequest, BuildTreeRequest, EstimateCostRequest
from lib.devnet import get_current_block, get_chain_id, get_safe_block, send_txs_stream
from lib.tree import build_tree_stream, get_tree_hierarchical, load_tree
from lib.cost import run_cost_estimator_stream, get_cost_model

# Load configuration
CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


config = load_config()

# FastAPI app
app = FastAPI(title="Hybrid Dispute Dashboard")

# State
state = {
    "tree_loaded": False,
    "tree_block_range": None,
    "last_block_range": None,
    "cost_data": None,
}


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the dashboard HTML."""
    html_path = Path(__file__).parent / "static" / "index.html"
    if html_path.exists():
        return FileResponse(html_path, media_type="text/html")
    return HTMLResponse("<h1>Hybrid Dispute Dashboard</h1><p>Setting up...</p>")


@app.get("/api/status")
async def get_status() -> StatusResponse:
    """Get current devnet and dashboard status."""
    l2_rpc = config.get("l2_rpc")
    l2_block = get_current_block(l2_rpc) if l2_rpc else None
    connected = l2_block is not None

    return StatusResponse(
        l1_block=None,
        l2_block=l2_block,
        connected=connected,
        tree_loaded=state["tree_loaded"],
        tree_block_range=state["tree_block_range"]
    )


@app.get("/api/config")
async def get_config():
    """Get non-sensitive config values for frontend."""
    return {
        "l2_rpc": config.get("l2_rpc"),
        "tree_output_path": config.get("tree_output_path"),
        "cost_model": config.get("cost_model", {})
    }


@app.post("/api/send-txs")
async def send_txs(req: SendTxsRequest):
    """Send transactions to L2 and stream progress via SSE."""

    async def event_generator():
        async for event in send_txs_stream(
            rpc_url=config["l2_rpc"],
            private_key=config["private_key"],
            account_address=config["account_address"],
            count=req.count
        ):
            # Store block range on completion
            if event.get("event") == "complete":
                data = event.get("data", {})
                state["last_block_range"] = [
                    data.get("block_start"),
                    data.get("block_end")
                ]

            yield {
                "event": event.get("event", "message"),
                "data": json.dumps(event.get("data", {}))
            }

    return EventSourceResponse(event_generator())


@app.get("/api/last-block-range")
async def get_last_block_range():
    """Get the block range from the last TX batch."""
    return {
        "block_range": state["last_block_range"]
    }


@app.post("/api/build-tree")
async def build_tree(req: BuildTreeRequest):
    """Build commitment tree and stream progress via SSE."""
    tree_path = config.get("tree_output_path", "./data/devnet_tree.json")

    async def event_generator():
        async for event in build_tree_stream(
            block_start=req.block_start,
            block_end=req.block_end,
            rpc_url=config["l2_rpc"],
            output_path=tree_path
        ):
            # Update state on completion
            if event.get("event") == "complete":
                state["tree_loaded"] = True
                state["tree_block_range"] = [req.block_start, req.block_end]

            yield {
                "event": event.get("event", "message"),
                "data": json.dumps(event.get("data", {}))
            }

    return EventSourceResponse(event_generator())


@app.get("/api/tree")
async def get_tree():
    """Get current tree in hierarchical format for visualization."""
    tree_path = config.get("tree_output_path", "./data/devnet_tree.json")
    result = get_tree_hierarchical(tree_path)

    if result is None:
        return {"error": "No tree loaded", "tree": None}

    return result


@app.get("/api/tree/raw")
async def get_tree_raw():
    """Get raw tree JSON (BFS format)."""
    tree_path = config.get("tree_output_path", "./data/devnet_tree.json")
    result = load_tree(tree_path)

    if result is None:
        return {"error": "No tree loaded"}

    return result


@app.post("/api/estimate-cost")
async def estimate_cost(req: EstimateCostRequest):
    """Run cost-estimator and stream progress via SSE."""
    op_path = config.get("op_succinct_path", "~/Downloads/op-succinct")

    async def event_generator():
        async for event in run_cost_estimator_stream(
            block_start=req.block_start,
            block_end=req.block_end,
            op_succinct_path=op_path
        ):
            # Store cost data on completion
            if event.get("event") == "complete":
                state["cost_data"] = event.get("data", {})

            yield {
                "event": event.get("event", "message"),
                "data": json.dumps(event.get("data", {}))
            }

    return EventSourceResponse(event_generator())


@app.get("/api/cost-model")
async def get_cost_model_endpoint(prove_price_usd: float = 0.34):
    """Get cost model with scenarios based on current data."""
    if not state["cost_data"]:
        return {"error": "No cost data available. Run estimate-cost first."}

    total_pgu = state["cost_data"].get("totalPgu", 0)
    cost_model_config = config.get("cost_model", {})

    return get_cost_model(
        total_pgu=total_pgu,
        prove_price_usd=prove_price_usd,
        config_cost_model=cost_model_config
    )


@app.get("/api/cost-data")
async def get_cost_data():
    """Get stored cost estimation data."""
    if not state["cost_data"]:
        return {"error": "No cost data available"}
    return state["cost_data"]


@app.get("/api/safe-block")
async def get_safe_block_endpoint():
    """Get latest safe block number."""
    l2_rpc = config.get("l2_rpc")
    safe = get_safe_block(l2_rpc) if l2_rpc else None
    return {"safe_block": safe}


if __name__ == "__main__":
    print(f"Starting Hybrid Dispute Dashboard on http://{config['host']}:{config['port']}")
    uvicorn.run(
        "server:app",
        host=config["host"],
        port=config["port"],
        reload=True
    )
