"""Pydantic models for request/response validation."""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class StatusResponse(BaseModel):
    l1_block: Optional[int] = None
    l2_block: Optional[int] = None
    connected: bool = False
    tree_loaded: bool = False
    tree_block_range: Optional[List[int]] = None


class SendTxsRequest(BaseModel):
    count: int = 5


class BuildTreeRequest(BaseModel):
    block_start: int
    block_end: int


class EstimateCostRequest(BaseModel):
    block_start: int
    block_end: int


class RunAllRequest(BaseModel):
    tx_count: int = 5
    prove_price_usd: float = 0.34


class CostScenario(BaseModel):
    label: str
    depth: int
    pgu: int
    prove: float
    usd: float


class CostModelResponse(BaseModel):
    prove_price_usd: float
    base_fee_prove: float
    pgu_price_per_bpgu: float
    scenarios: List[CostScenario]
