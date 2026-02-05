"""Commitment tree building and manipulation."""

import json
import math
import subprocess
from pathlib import Path
from typing import AsyncGenerator, List, Optional
from web3 import Web3


def get_state_root(block_num: int, rpc_url: str) -> Optional[str]:
    """Get state root for a block using cast."""
    try:
        result = subprocess.run(
            ["cast", "block", "--rpc-url", rpc_url, str(block_num), "--json"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            block = json.loads(result.stdout)
            return block.get("stateRoot")
        return None
    except Exception as e:
        return None


def build_bfs_tree(leaves: List[bytes]) -> List[bytes]:
    """
    Build a binary Merkle tree in BFS order from leaves.

    Returns array where:
    - index 0 = root
    - index 2i+1 = left child of i
    - index 2i+2 = right child of i
    """
    n = len(leaves)
    if n == 0:
        return []

    # Tree has 2n-1 nodes for n leaves
    tree_size = 2 * n - 1
    tree = [b'\x00' * 32] * tree_size

    # Place leaves at the end
    leaf_start = n - 1
    for i, leaf in enumerate(leaves):
        tree[leaf_start + i] = leaf

    # Build internal nodes bottom-up
    for i in range(leaf_start - 1, -1, -1):
        left = tree[2 * i + 1]
        right = tree[2 * i + 2]
        tree[i] = Web3.keccak(left + right)

    return tree


def bfs_to_hierarchical(
    bfs_array: List[str],
    block_start: int,
    block_end: int,
    depth: int
) -> dict:
    """
    Convert BFS array to hierarchical structure for D3.js.

    Each node gets:
    - name: shortened hash
    - hash: full hash
    - depth: level in tree
    - blockRange: [start, end] blocks covered
    - children: child nodes (if not leaf)
    """
    if not bfs_array:
        return {}

    num_blocks = block_end - block_start + 1

    def build_node(index: int, level: int, range_start: int, range_end: int) -> dict:
        if index >= len(bfs_array):
            return None

        hash_val = bfs_array[index]
        is_leaf = level == depth

        node = {
            "name": hash_val[:10] + "...",
            "hash": hash_val,
            "depth": level,
            "blockRange": [range_start, range_end],
            "isLeaf": is_leaf
        }

        if not is_leaf:
            mid = (range_start + range_end) // 2
            left_idx = 2 * index + 1
            right_idx = 2 * index + 2

            children = []
            left = build_node(left_idx, level + 1, range_start, mid)
            right = build_node(right_idx, level + 1, mid + 1, range_end)

            if left:
                children.append(left)
            if right:
                children.append(right)

            if children:
                node["children"] = children

        return node

    return build_node(0, 0, block_start, block_end)


async def build_tree_stream(
    block_start: int,
    block_end: int,
    rpc_url: str,
    output_path: str
) -> AsyncGenerator[dict, None]:
    """
    Build commitment tree and yield progress updates.
    """
    yield {
        "event": "progress",
        "data": {
            "step": "started",
            "message": f"Building tree for blocks {block_start} → {block_end}"
        }
    }

    num_blocks = block_end - block_start + 1

    # Collect state roots
    state_roots = []
    blocks_info = []

    for i, block_num in enumerate(range(block_start, block_end + 1)):
        yield {
            "event": "progress",
            "data": {
                "step": "collecting",
                "current": block_num,
                "index": i + 1,
                "total": num_blocks,
                "message": f"Collecting state root {i + 1}/{num_blocks} (block {block_num})"
            }
        }

        root = get_state_root(block_num, rpc_url)
        if root is None:
            yield {
                "event": "error",
                "data": {"message": f"Failed to get state root for block {block_num}"}
            }
            return

        state_roots.append(root)
        blocks_info.append({
            "number": block_num,
            "stateRoot": root
        })

    yield {
        "event": "progress",
        "data": {
            "step": "building",
            "message": f"Collected {len(state_roots)} state roots, building tree..."
        }
    }

    # Pad to power of 2
    depth = max(1, math.ceil(math.log2(len(state_roots)))) if len(state_roots) > 1 else 1
    padded_size = 2 ** depth
    padding_needed = padded_size - len(state_roots)

    # Pad with last state root (or zeros)
    padded_roots = state_roots.copy()
    padding_hash = state_roots[-1] if state_roots else "0x" + "00" * 32
    for _ in range(padding_needed):
        padded_roots.append(padding_hash)

    # Convert to bytes for hashing
    leaves_bytes = [bytes.fromhex(r[2:]) if r.startswith("0x") else bytes.fromhex(r) for r in padded_roots]

    # Build tree
    tree_bytes = build_bfs_tree(leaves_bytes)
    tree_hex = ["0x" + node.hex() for node in tree_bytes]

    # Create output structure
    result = {
        "scenario": "devnet_tree",
        "blockStart": block_start,
        "blockEnd": block_end,
        "depth": depth,
        "numBlocks": num_blocks,
        "numLeaves": padded_size,
        "paddingLeaves": padding_needed,
        "rootCommitment": tree_hex[0] if tree_hex else None,
        "blocks": blocks_info,
        "commitmentsBFS": tree_hex
    }

    # Save to file
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)

    yield {
        "event": "complete",
        "data": {
            "depth": depth,
            "total_nodes": len(tree_hex),
            "leaves": padded_size,
            "actual_blocks": num_blocks,
            "padding": padding_needed,
            "root": tree_hex[0] if tree_hex else None,
            "path": str(output_path)
        }
    }


def load_tree(path: str) -> Optional[dict]:
    """Load tree from JSON file."""
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def get_tree_hierarchical(path: str) -> Optional[dict]:
    """Load tree and convert to hierarchical format for D3.js."""
    tree_data = load_tree(path)
    if not tree_data:
        return None

    return {
        "metadata": {
            "blockStart": tree_data.get("blockStart"),
            "blockEnd": tree_data.get("blockEnd"),
            "depth": tree_data.get("depth"),
            "totalNodes": len(tree_data.get("commitmentsBFS", [])),
            "rootCommitment": tree_data.get("rootCommitment")
        },
        "tree": bfs_to_hierarchical(
            tree_data.get("commitmentsBFS", []),
            tree_data.get("blockStart", 0),
            tree_data.get("blockEnd", 0),
            tree_data.get("depth", 0)
        ),
        "blocks": tree_data.get("blocks", [])
    }
