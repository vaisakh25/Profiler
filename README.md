# Agentic Data Profiler

A production-grade data profiling engine exposed as an **MCP (Model Context Protocol) server**. Profile CSV, Parquet, and other tabular data files — detect schemas, infer types, assess quality, and discover cross-table foreign key relationships. Deploy anywhere as a container and connect any MCP-compatible agent.

## Key Features

- **11-layer profiling pipeline** — intake validation, content-sniffing format detection, memory-safe size strategy, format-specific engines, column standardization, type inference with confidence scoring, structural quality checks, and cross-table relationship detection.
- **MCP server** — 6 tools, 2 resources, 3 prompt templates. Connect from LangGraph, Claude Desktop, Claude Code, or any MCP client.
- **Format-agnostic output** — identical JSON profile schema regardless of source format (CSV, Parquet, JSON, Excel).
- **Memory-safe** — three-tier read strategy (MEMORY_SAFE / LAZY_SCAN / STREAM_ONLY) auto-selected based on file size. Handles multi-GB files without OOM.
- **Content sniffing** — never trusts file extensions. Detects format via magic bytes and structural analysis.
- **Containerized** — Dockerfile and docker-compose included. Deploy on Docker, Cloud Run, ECS, Azure Container Apps, or Kubernetes.

## Architecture

```
MCP Client (LangGraph / Claude Desktop / Custom)
        │
        │  MCP Protocol (stdio or SSE)
        ▼
┌──────────────────────────────────┐
│       MCP Server (FastMCP)       │
│                                  │
│  Tools:                          │
│   profile_file                   │
│   profile_directory              │
│   detect_relationships           │
│   list_supported_files           │
│   upload_file                    │
│   get_quality_summary            │
│                                  │
│  Resources:                      │
│   profiles://{table_name}        │
│   relationships://latest         │
│                                  │
│  Prompts:                        │
│   summarize_profile              │
│   migration_readiness            │
│   quality_report                 │
└───────────────┬──────────────────┘
                │
                ▼
┌──────────────────────────────────┐
│     Profiling Pipeline           │
│                                  │
│  Intake → Classification →       │
│  Size Strategy → Engine →        │
│  Standardization → Column        │
│  Profiling → Type Inference →    │
│  Quality Checks → Relationship   │
│  Detection → JSON Output         │
└──────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- pip

### Install

```bash
# Clone the repository
git clone <repo-url>
cd Agentic_Data_Profiler_Files

# Install in editable mode
pip install -e ".[dev]"
```

### Run the MCP Server

```bash
# stdio transport (local — for Claude Desktop, Claude Code, LangGraph)
python -m file_profiler --transport stdio

# SSE transport (remote — for containerized deployment)
python -m file_profiler --transport sse --host 0.0.0.0 --port 8080
```

### Use as a Python Library

```python
from file_profiler import profile_file, profile_directory, analyze_relationships

# Profile a single file
profile = profile_file("data/customers.csv")
print(profile.row_count, len(profile.columns))

# Profile all files in a directory
profiles = profile_directory("data/", parallel=True)

# Detect cross-table relationships
report = analyze_relationships(profiles)
for fk in report.candidates:
    print(f"{fk.fk.table_name}.{fk.fk.column_name} → "
          f"{fk.pk.table_name}.{fk.pk.column_name} "
          f"(confidence: {fk.confidence:.2f})")
```

## Docker Deployment

### Build and Run

```bash
# Using docker compose
docker compose up -d

# Server available at http://localhost:8080/sse
```

### Connect Your Agent

Point your MCP client to the SSE endpoint:

```json
{
  "mcpServers": {
    "file-profiler": {
      "url": "http://localhost:8080/sse"
    }
  }
}
```

### Volume Mounts

Place your data files in the `./data` directory. They are mounted read-only at `/data/mounted` inside the container. Alternatively, use the `upload_file` tool to send files via base64.

## MCP Tools Reference

| Tool | Description |
|------|-------------|
| `profile_file(file_path)` | Profile a single file through the full 11-layer pipeline. Returns FileProfile with columns, types, quality flags, and statistics. |
| `profile_directory(dir_path, parallel)` | Profile all supported files in a directory. Returns a list of FileProfile dicts. |
| `detect_relationships(dir_path, confidence_threshold)` | Detect foreign key relationships across tables. Scores by name similarity, type compatibility, cardinality, and value overlap. |
| `list_supported_files(dir_path)` | List files the profiler can handle (intake + classification only, no full profiling). |
| `upload_file(file_name, file_content_base64)` | Upload a base64-encoded file to the server. Returns the server-side path for use with `profile_file`. |
| `get_quality_summary(file_path)` | Get quality summary for a file. Returns cached results if available. |

## Pipeline Layers

| Layer | Module | Purpose |
|-------|--------|---------|
| 1 | `intake/validator.py` | File existence, encoding detection (BOM + chardet), compression detection, delimiter sniffing |
| 2 | `classification/classifier.py` | Content-sniffing format detection via magic bytes (Parquet, Excel, JSON, CSV) |
| 3 | `strategy/size_strategy.py` | Auto-select MEMORY_SAFE (<100 MB), LAZY_SCAN (100 MB–2 GB), or STREAM_ONLY (>2 GB) |
| 4 | `engines/csv_engine.py` | CSV structure detection, header detection, row counting, sampling (Vitter's Algorithm R) |
| 5 | `engines/parquet_engine.py` | Parquet metadata reading, schema flattening, column-pruned row-group iteration |
| 6.5 | `standardization/normalizer.py` | Name normalization, null sentinel detection, boolean unification, numeric cleaning |
| 7 | `profiling/column_profiler.py` | Statistics: null count, distinct count, min/max, cardinality, top-N values, string length distribution |
| 7.5 | `profiling/type_inference.py` | Type detection with 90% confidence threshold (INTEGER, FLOAT, DATE, TIMESTAMP, UUID, BOOLEAN, CATEGORICAL, FREE_TEXT, STRING) |
| 8 | `quality/structural_checker.py` | Quality flags: duplicate columns, fully null, constant, high null ratio, column shift errors, encoding inconsistency |
| 9 | `analysis/relationship_detector.py` | Cross-table FK scoring: name similarity (0.50), type compatibility (0.20), cardinality (0.25), value overlap (0.15) |
| 11 | `output/profile_writer.py` | Atomic JSON serialization with QualitySummary computation |

## Project Structure

```
Agentic_Data_Profiler_Files/
├── file_profiler/                  # Main package
│   ├── __init__.py                 # Public API exports
│   ├── __main__.py                 # python -m file_profiler entry point
│   ├── main.py                     # Pipeline orchestrator
│   ├── mcp_server.py               # MCP server (tools, resources, prompts)
│   ├── analysis/                   # Cross-table relationship detection
│   ├── classification/             # Format detection via content sniffing
│   ├── config/
│   │   ├── settings.py             # Pipeline tuning constants
│   │   └── env.py                  # Environment-based deployment config
│   ├── engines/                    # Format-specific profiling engines
│   │   ├── csv_engine.py
│   │   └── parquet_engine.py
│   ├── intake/                     # File validation and encoding detection
│   ├── models/                     # Data classes and enums
│   ├── output/                     # JSON serialization and ER diagrams
│   ├── profiling/                  # Column profiling and type inference
│   ├── quality/                    # Structural quality checks
│   ├── standardization/            # Data normalization
│   ├── strategy/                   # Size-based read strategy selection
│   └── utils/                      # File resolver, logging setup
├── tests/                          # pytest test suite (305 tests)
├── data/                           # Sample data and output profiles
├── pyproject.toml                  # Package metadata and dependencies
├── Dockerfile                      # Container image definition
├── docker-compose.yml              # Orchestration with volumes
└── requirements.txt                # Dependency pinning
```

## Configuration

### Pipeline Settings (`file_profiler/config/settings.py`)

| Setting | Default | Description |
|---------|---------|-------------|
| `MEMORY_SAFE_MAX_BYTES` | 100 MB | Threshold for full in-memory load |
| `LAZY_SCAN_MAX_BYTES` | 2 GB | Threshold for chunked/lazy reads |
| `SAMPLE_ROW_COUNT` | 10,000 | Rows held in reservoir sample |
| `CATEGORICAL_MAX_DISTINCT` | 50 | Max distinct values for CATEGORICAL type |
| `NULL_HEAVY_THRESHOLD` | 0.70 | Null ratio to flag HIGH_NULL_RATIO |
| `MAX_PARALLEL_WORKERS` | 4 | Parallel file processing workers |

### Environment Variables (deployment)

| Variable | Default | Description |
|----------|---------|-------------|
| `PROFILER_DATA_DIR` | `/data` | Root directory for data files |
| `PROFILER_UPLOAD_DIR` | `/data/uploads` | Upload storage directory |
| `PROFILER_OUTPUT_DIR` | `/data/output` | Profile output directory |
| `MAX_UPLOAD_SIZE_MB` | `500` | Maximum upload file size |
| `MCP_TRANSPORT` | `stdio` | Transport protocol (`stdio`, `sse`) |
| `MCP_HOST` | `0.0.0.0` | Server bind host |
| `MCP_PORT` | `8080` | Server bind port |
| `LOG_LEVEL` | `INFO` | Logging level |

## Testing

```bash
# Run the full test suite
pytest

# Run with coverage
pytest --cov=file_profiler --cov-report=term-missing

# Run specific test module
pytest tests/test_mcp_server.py -v
```

## Supported Formats

| Format | Status | Engine |
|--------|--------|--------|
| CSV (including .tsv, .dat, .psv) | Supported | `csv_engine.py` |
| Parquet (.parquet, .pq, .parq) | Supported | `parquet_engine.py` |
| Gzip-compressed CSV | Supported | Transparent decompression |
| ZIP archives (single or multi-CSV) | Supported | Partition-aware profiling |
| JSON / NDJSON | Planned | Design complete |
| Excel (.xlsx, .xls) | Planned | Design complete |

## Output Schema

Every profiled file produces a unified `FileProfile` JSON structure:

```json
{
  "source_type": "file",
  "file_format": "csv",
  "table_name": "customers",
  "row_count": 10500,
  "is_row_count_exact": true,
  "encoding": "utf-8",
  "size_bytes": 524288,
  "size_strategy": "MEMORY_SAFE",
  "columns": [
    {
      "name": "customer_id",
      "inferred_type": "INTEGER",
      "confidence_score": 1.0,
      "null_count": 0,
      "distinct_count": 10500,
      "cardinality": "HIGH",
      "is_key_candidate": true,
      "quality_flags": [],
      "top_values": [{"value": "1", "count": 1}],
      "sample_values": ["1", "2", "3"]
    }
  ],
  "structural_issues": [],
  "quality_summary": {
    "columns_profiled": 12,
    "columns_with_issues": 0,
    "null_heavy_columns": 0,
    "type_conflict_columns": 0,
    "corrupt_rows_detected": 0
  }
}
```

## License

Proprietary. All rights reserved.
