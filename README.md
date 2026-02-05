# Hybrid Dispute Resolution Emulator

Optimistic rollup에서 **bisection + ZK proof**를 결합한 hybrid dispute resolution의 비용 분석 및 시뮬레이션 도구.

## Overview

기존 optimistic rollup의 dispute resolution은 두 가지 접근법이 있습니다:

1. **Interactive Bisection** (Cannon, BOLD): O(log N) 트랜잭션, 게임 이론적 보안
2. **Pure ZKP**: 1 트랜잭션, 암호학적 보안, 하지만 큰 배치에서 비용 급증

이 프로젝트는 **Hybrid Approach**를 시뮬레이션합니다:
- Pre-committed bisection으로 disagreement 지점을 빠르게 좁힘 (3-4 TX)
- 최종 단계에서만 작은 세그먼트에 대해 ZK proof 제출
- O(log G) 비용 스케일링으로 배치 크기와 무관하게 일정한 dispute 비용

## Features

- **OP Succinct cost-estimator 연동**: 실제 L2 블록에 대한 PGU(Proving Gas Unit) 측정
- **Cost Model 시뮬레이션**: bisection depth별 비용 계산
- **Commitment Tree 시각화**: D3.js 기반 interactive tree viewer
- **FastAPI 웹 대시보드**: 실시간 SSE 로깅

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Web Dashboard                         │
│  - Send L2 TXs (via cast)                               │
│  - Build commitment tree from state roots               │
│  - Run OP Succinct cost-estimator                       │
│  - Visualize tree & cost analysis                       │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Server                        │
│  - SSE streaming for real-time updates                  │
│  - REST API for status, config, tree data               │
└─────────────────────────────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         L2 Devnet    OP Succinct    Tree Builder
         (cast)     (cost-estimator)  (Python)
```

## Prerequisites

- Python 3.10+
- [Foundry](https://book.getfoundry.sh/) (cast CLI)
- [OP Succinct](https://github.com/succinctlabs/op-succinct) (cost-estimator)
- Running L2 devnet (e.g., Kurtosis)

## Installation

```bash
# Clone repository
git clone https://github.com/tokamak-network/hybrid-dispute-emulator.git
cd hybrid-dispute-emulator

# Install Python dependencies
pip install -r requirements.txt

# Copy and configure
cp config.yaml config.local.yaml
# Edit config.local.yaml with your devnet RPC endpoints
```

## Configuration

`config.yaml`:

```yaml
# Network RPC endpoints
l1_rpc: "http://127.0.0.1:8545"
l2_rpc: "http://127.0.0.1:61187"

# Account for TX signing (devnet prefunded account)
private_key: "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
account_address: "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

# OP Succinct path
op_succinct_path: "~/Downloads/op-succinct"

# Cost model constants
cost_model:
  compressed_base_fee: 0.2      # Range proof base fee (PROVE)
  compressed_pgu_price: 0.45    # Range proof PGU price (PROVE/bPGU)
  plonk_fee: 0.3                # Aggregation proof fixed fee (PROVE)
  prove_price_usd: 0.34         # PROVE token price (USD)
```

## Usage

```bash
# Start the dashboard server
python server.py

# Open browser
open http://localhost:8080
```

### Dashboard Workflow

1. **Send TXs**: L2에 테스트 트랜잭션 전송
2. **Build Tree**: 블록 범위에서 state root 수집 후 commitment tree 생성
3. **Estimate Cost**: OP Succinct cost-estimator로 PGU 측정
4. **View Results**: Tree 시각화 및 bisection depth별 비용 비교

## Cost Model

```
C(d) = compressed_base_fee + (bPGU × compressed_pgu_price) + plonk_fee
```

Where:
- `bPGU = total_PGU / 10^9 / 2^d` (billion PGU after d bisection steps)
- `d` = bisection depth

| Depth | Remaining bPGU | Compressed | Plonk | Total (PROVE) |
|-------|----------------|------------|-------|---------------|
| 0     | 10.0           | 4.70       | 0.30  | 5.00          |
| 5     | 0.31           | 0.34       | 0.30  | 0.64          |
| 7     | 0.08           | 0.24       | 0.30  | 0.54          |
| 10    | 0.01           | 0.20       | 0.30  | 0.50          |
| 11    | 0.005          | 0.20       | 0.30  | 0.50          |

**Optimal depth**: d=10-11 (10x cost reduction vs pure ZKP)

## Project Structure

```
hybrid-dispute-emulator/
├── server.py              # FastAPI server
├── config.yaml            # Configuration
├── requirements.txt       # Python dependencies
├── lib/
│   ├── models.py          # Pydantic models
│   ├── devnet.py          # L2 interaction (cast)
│   ├── tree.py            # Commitment tree builder
│   └── cost.py            # Cost estimation
├── static/
│   └── index.html         # Dashboard UI (D3.js)
└── data/                   # Generated tree data (gitignored)
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard HTML |
| `/api/status` | GET | Current connection status |
| `/api/config` | GET | Non-sensitive config values |
| `/api/send-txs` | POST | Send L2 transactions (SSE) |
| `/api/build-tree` | POST | Build commitment tree (SSE) |
| `/api/estimate-cost` | POST | Run cost estimator (SSE) |
| `/api/tree` | GET | Get hierarchical tree data |
| `/api/tree/raw` | GET | Get raw tree JSON (BFS format) |
| `/api/cost-model` | GET | Get cost model calculations |
| `/api/safe-block` | GET | Get latest safe block number |

## License

MIT
