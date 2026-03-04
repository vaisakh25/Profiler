# File Profiling Branch — Architecture & Design Document

## Overview

The File Profiling branch handles profiling of raw files (CSV, JSON, Parquet, Excel) as the input source — as opposed to live database tables. It is the second major branch of the Data Profiling Tool and is critical for legacy modernization projects, where source data arrives as file exports rather than structured databases.

The output of this branch is **format-agnostic**: regardless of whether the source was a CSV or a Parquet file, the final profile object is identical to the database profiling output, allowing downstream Silver/Gold layer logic to remain source-unaware.

---

## Design Principles

- **Never trust the file extension.** Use content sniffing (magic bytes) to determine format.
- **Never load large files fully into memory.** Use lazy reads, chunked streaming, or DuckDB pushdown.
- **Be defensive at every layer.** Files are corrupted, partial, misformatted, and misrepresented far more often than database tables.
- **Tolerate partial corruption.** Log bad rows and continue — do not abort the entire profile.
- **Unified output.** Every file type produces the same JSON profile schema.

---

## Pipeline Overview

```
File Intake Layer
      │
      ▼
File Type Classification
      │
      ▼
Size Strategy Selection
      │
      ├─── CSV ──────► CSV Profiling Engine
      ├─── Parquet ──► Parquet Profiling Engine
      ├─── JSON ─────► JSON Profiling Engine
      └─── Excel ────► Excel Profiling Engine
                              │
                              ▼
                   Column Profiling Engine
                              │
                              ▼
                  Structural Quality Checks
                              │
                              ▼
                   Column Intelligence Layer
                              │
                              ▼
                      Unified Output (JSON)
```

---

## Layer 1 — File Intake

**Purpose:** Validate the file is readable and well-formed before any profiling begins.

**Checks performed:**

| Check               | Failure Behavior         |
|---------------------|--------------------------|
| File exists         | Raise `FileNotFoundError` |
| File size > 0       | Raise `EmptyFileError`   |
| Encoding detection  | Log, attempt UTF-8 fallback |
| Delimiter detection | Best-guess via content sniff |
| Compression check   | Detect `.gz`, `.zip`, decompress before read |

**Critical edge cases:**
- Corrupted or partially uploaded files
- Binary files with a `.csv` extension
- Excel files renamed to `.csv`
- BOM (Byte Order Mark) characters at file start (`\xef\xbb\xbf`)
- UTF-16 encoded files

**Rule:** Validation must complete successfully before any downstream layer is invoked.

---

## Layer 2 — File Type Classification

**Purpose:** Determine the actual file format using content sniffing, not extension.

**Detection method — magic bytes / structure inspection:**

| Format   | Detection Signal                          |
|----------|-------------------------------------------|
| Parquet  | Magic bytes `PAR1` at file start and end  |
| JSON     | Starts with `{` or `[`, or valid NDJSON   |
| CSV      | Consistent delimiter pattern across rows  |
| Excel    | OLE2 or ZIP (XLSX) magic bytes            |
| UNKNOWN  | None of the above match                   |

**Why extension is unreliable:**
- Ops teams frequently rename files during transfers
- ETL exports sometimes write wrong extensions
- Compressed files may strip extensions

If format is `UNKNOWN`, flag the file and skip profiling — do not attempt to force-read.

---

## Layer 3 — Size Strategy Selection

**Purpose:** Determine the read strategy before touching the file data, to avoid OOM errors.

**Thresholds:**

| Strategy      | File Size     | Behavior                                         |
|---------------|---------------|--------------------------------------------------|
| `MEMORY_SAFE` | < 100 MB      | Load fully into memory, standard read            |
| `LAZY_SCAN`   | 100 MB – 2 GB | Chunked reads, Polars lazy frames, DuckDB scan   |
| `STREAM_ONLY` | > 2 GB        | Stream line-by-line, never materialize full set  |

The size strategy is passed as a parameter to all downstream format-specific profiling engines.

---

## Layer 4 — CSV Profiling Engine

CSV is the most complex format to profile reliably because it has no enforced schema and a wide range of structural variants.

### Step A — Structure Detection

Before reading any data rows, detect:

| Property                | Method                                     |
|-------------------------|--------------------------------------------|
| Delimiter               | Frequency analysis of `,` `/` `\t` `\|`   |
| Quote character         | Scan for `"` or `'` wrapping               |
| Escape character        | Look for `\\` or doubled quotes            |
| Header presence         | Heuristic on first row (see Step B)        |
| Line ending type        | `\n` vs `\r\n`                             |
| Inconsistent row widths | Count fields per row across first 100 rows |

**Structural corruption flag:** If inconsistent row lengths exceed a threshold (e.g., >5% of sampled rows), flag the file as structurally corrupt before profiling continues.

**Edge cases to handle:**
- Embedded commas inside quoted fields
- Multiline quoted fields
- Unescaped quotes mid-value
- Irregular row widths at end of file (truncated export)
- Corrupt rows embedded in the middle of an otherwise clean file

### Step B — Header Detection

Read the first 5 rows and apply heuristics:

| Signal                                          | Interpretation     |
|-------------------------------------------------|--------------------|
| Row 1 is all non-numeric and all unique values  | Header present     |
| Row 1 contains repeated values or numbers       | No header, generate `column_1, column_2 ...` |
| Row 1 has any null/empty cells                  | Suspicious — flag  |

Generated column names must be stable across re-reads.

### Step C — Row Count Estimation

**Do not count line-by-line for large files.** Use one of:
- Chunk-and-extrapolate: read N chunks, average rows per byte, multiply by file size
- OS-level size estimate: `file_size / avg_bytes_per_row`
- Stream count with chunking: accumulate count without holding rows in memory

Store as `estimated_row_count` with a `is_exact` flag.

### Step D — Sampling Strategy

| File Size    | Method                                    |
|--------------|-------------------------------------------|
| < 100 MB     | Full read into memory                     |
| 100 MB – 2 GB| Chunked read, reservoir sample N rows     |
| > 2 GB       | Stream with skip-interval (every Kth row) |

**Never use:**
```python
df = pandas.read_csv(large_file)   # OOM risk
```

**Use instead:**
- `pandas.read_csv(chunksize=...)`
- `polars.scan_csv(...)` with lazy evaluation
- `duckdb.query("SELECT * FROM read_csv_auto(...) LIMIT N")`

### Step E — Type Inference Engine

CSV has no declared types — everything starts as string. Apply ordered detection per column on the sampled rows:

**Inference order (most specific to least):**

1. All null → `NULL_ONLY`
2. All values match integer pattern → `INTEGER`
3. All values match float/decimal pattern → `FLOAT`
4. All values are `true/false/yes/no/1/0` → `BOOLEAN`
5. All values match ISO date pattern → `DATE`
6. All values match ISO timestamp pattern → `TIMESTAMP`
7. All values match UUID pattern → `UUID`
8. Low cardinality (< N distinct values) → `CATEGORICAL`
9. Long average length → `FREE_TEXT`
10. Default → `STRING`

**Output per column:**
```json
{
  "inferred_type": "DATE",
  "confidence_score": 0.97
}
```

**Never overwrite the raw string value** — store inferred type separately.

**Edge cases requiring special handling:**

| Issue                             | Strategy                                      |
|-----------------------------------|-----------------------------------------------|
| Mixed numeric + null              | Treat as nullable integer                     |
| Numbers with commas (`1,000`)     | Strip commas before numeric check             |
| Mixed date formats in one column  | Flag as `MIXED_DATE`, store format variants   |
| Timestamps with mixed timezones   | Normalize to UTC, flag inconsistency          |
| Leading zeros (`00123`)           | Keep as STRING — likely zip code or ID        |

---

## Layer 5 — Parquet Profiling Engine

Parquet is self-describing, making it significantly easier than CSV — but nested types require careful handling.

### Step A — Read Schema Without Data Scan

```python
metadata = read_parquet_metadata(path)
row_count   = metadata.row_count
schema      = metadata.schema   # declared types, no I/O needed
```

Zero data rows are read at this stage.

### Step B — Detect and Flatten Nested Fields

Parquet supports nested types that must be surfaced as flat columns:

| Parquet Type | Example                        | Flattened Name              |
|--------------|--------------------------------|-----------------------------|
| Struct       | `user.address.city`            | `user_address_city`         |
| List         | `order.items[]`                | `order_items_0`, exploded   |
| Map          | `attributes.{key: value}`      | `attributes_<key>`          |

A **field mapping dictionary** must be persisted alongside the profile so the original path can be reconstructed later.

### Step C — Column-Level Profiling via Pushdown

Use DuckDB to push aggregations down into the Parquet file — do not load into memory:

```sql
SELECT
    COUNT(*)              AS total,
    COUNT(DISTINCT col)   AS unique_count,
    MIN(col)              AS min_val,
    MAX(col)              AS max_val
FROM parquet_scan('file.parquet')
```

### Step D — Large Multi-GB Parquet Strategy

- Profile one column at a time
- Never `SELECT *` on multi-GB files
- Use column pruning: `SELECT col1 FROM parquet_scan(...)`
- Avoid materializing the full dataset at any point

---

## Layer 6 — JSON Profiling Engine

JSON is the hardest file format to profile due to its schema flexibility and nesting depth.

### Step A — Detect JSON Shape

| Shape                 | Detection                                        |
|-----------------------|--------------------------------------------------|
| Single object         | File starts with `{`, top-level is one record    |
| Array of objects      | File starts with `[`, top-level is an array      |
| Newline-delimited JSON (NDJSON) | Each line is a valid `{}` object       |
| Deep nested structure | Any of the above with objects inside objects     |

Shape determines the read strategy for all downstream steps.

### Step B — Schema Discovery via Union

Stream-parse the first N records (default: 1,000). For each record:
- Collect all keys (recursively for nested objects)
- Track the observed type(s) per key across all records
- Track how many records contain each key (`occurrence_ratio`)

**Output:**
```python
{
  "column_name": "order.customer.id",
  "observed_types": {"string", "null"},
  "occurrence_ratio": 0.98   # present in 98% of records
}
```

**Critical edge cases:**
- Same key holds different types across records → flag as `TYPE_CONFLICT`
- Keys missing from some records → reflected in `occurrence_ratio < 1.0`
- Arrays of objects inside a field → must decide flatten vs. keep-as-string

### Step C — Flatten Strategy

Three options (configurable):

| Strategy      | Behavior                                              | Use When                        |
|---------------|-------------------------------------------------------|---------------------------------|
| `EXPLODE`     | Arrays expand into multiple rows                      | Small arrays, need row-level access |
| `STRINGIFY`   | Nested objects/arrays kept as JSON string column      | Deep nesting, preserve structure |
| `HYBRID`      | Flatten known shallow fields, stringify deep arrays   | General purpose (recommended)   |

**Rule:** Never blindly explode large arrays — a single record with a 10,000-item array would produce 10,000 rows, destroying row count integrity.

---

## Layer 7 — Column Profiling Engine (File Path)

After type inference and schema discovery, compute the standard column metrics. This layer is **shared across all file formats**.

**Metrics computed:**

| Metric                  | Large File Strategy                        |
|-------------------------|--------------------------------------------|
| `null_count`            | Exact count from sample                    |
| `distinct_count`        | Approximate via hash sampling if > 1M rows |
| `min` / `max`           | Exact for numeric/date; lexicographic for string |
| `string_length_distribution` | P10, P50, P90, max                    |
| `top_N_values`          | Top 10 most frequent values + counts       |
| `skewness`              | Numeric columns only                       |
| `avg_length`            | Mean string length                         |

**Approximate distinct count:** For very large columns, use hash-modulo sampling to estimate cardinality without materializing all unique values.

---

## Layer 8 — Structural Quality Checks

File-specific structural issues that do not exist in well-managed databases:

| Check                    | Description                                                    |
|--------------------------|----------------------------------------------------------------|
| Duplicate column names   | Two columns with the same header name                         |
| Fully null columns       | Every value in the column is null                             |
| Constant columns         | Only one distinct non-null value                              |
| High-null ratio          | > 70% of rows are null for a column                          |
| Column shift errors      | Row has fewer/more fields than header (misalignment)          |
| Encoding inconsistencies | Mixed UTF-8 and Latin-1 within same file                     |

Each check produces a `quality_flag` entry in the column profile.

---

## Layer 9 — Legacy Flat File Handling

Fixed-width and legacy export files are a special case that require positional parsing rather than delimiter detection.

**Fixed-width files:**
- Require a **position mapping config** (column name → start/end byte position)
- No delimiter detection applies
- Column boundaries are absolute character positions
- Values are right/left padded — strip before type inference

**Other legacy patterns:**

| Pattern                  | Handling                                              |
|--------------------------|-------------------------------------------------------|
| Encoded date formats     | Map legacy format (e.g., `YYYYMMDD`) to ISO           |
| Truncated values         | Flag columns where max length == field width exactly  |
| Multi-line logical records | Buffer lines until record terminator is found       |

---

## Layer 10 — Performance Strategy

| Rule                                              | Reason                                      |
|---------------------------------------------------|---------------------------------------------|
| Process one file at a time                        | Avoids memory contention between large files |
| Never hold full dataset in memory for large files | OOM protection                              |
| Release memory after each file's profile is saved | Allow GC to reclaim before next file        |
| Persist profile immediately after each file       | Prevents loss on crash mid-batch            |
| Use DuckDB for all SQL-style aggregations on files | Pushdown avoids full materialization        |

**Recommended readers by format:**

| Format  | Recommended Tool                           |
|---------|--------------------------------------------|
| CSV     | `duckdb.read_csv_auto`, `polars.scan_csv`  |
| Parquet | `duckdb.parquet_scan`, `pyarrow.parquet`   |
| JSON    | `orjson` for streaming parse               |
| Excel   | `openpyxl` (never `xlrd` for XLSX)         |

---

## Layer 11 — Unified Output Schema

Regardless of source file format, the output profile must be identical to the database profiling output. This makes the downstream Silver layer completely source-agnostic.

```json
{
  "source_type": "file",
  "file_format": "csv",
  "file_path": "/data/exports/orders_2024.csv",
  "table_name": "orders_2024",
  "row_count": 150000,
  "is_row_count_exact": true,
  "encoding": "utf-8",
  "size_strategy": "LAZY_SCAN",

  "columns": [
    {
      "name": "order_id",
      "declared_type": null,
      "inferred_type": "INTEGER",
      "confidence_score": 0.99,
      "null_count": 0,
      "distinct_count": 150000,
      "unique_ratio": 1.0,
      "cardinality": "HIGH",
      "min": "1",
      "max": "150000",
      "avg_length": 5.2,
      "is_nullable": false,
      "is_constant": false,
      "is_sparse": false,
      "is_key_candidate": true,
      "is_low_cardinality": false,
      "semantic_type": "identifier",
      "quality_flags": [],
      "sample_values": ["1", "2", "3"]
    }
  ],

  "structural_issues": [],
  "quality_summary": {
    "columns_profiled": 12,
    "columns_with_issues": 1,
    "null_heavy_columns": 0,
    "type_conflict_columns": 0,
    "corrupt_rows_detected": 0
  }
}
```

---

## Layer 12 — Advanced Edge Cases

| Scenario                             | Handling Strategy                                         |
|--------------------------------------|-----------------------------------------------------------|
| 10M rows, 3 columns                  | Stream count, full column-level scan via DuckDB           |
| 10 columns, 2GB single text column   | Profile other columns normally; skip stats on text column |
| CSV with 20% corrupted rows          | Log bad rows, profile on clean rows, flag corruption rate |
| JSON with 50% records missing a key  | Track `occurrence_ratio`, mark column as optional         |
| UTF-16 encoding                      | Detect via BOM, transcode to UTF-8 before read            |
| Multi-file partition (folder of CSVs)| Treat as single logical table, union schema across files  |
| Incremental drop files               | Compare schema against previous profile; flag drift       |

---

## Integration with Database Branch

The file profiling branch produces the same output schema as the database branch. Both feed into the shared **Column Intelligence Layer**:

```
Database Branch ──┐
                  ├──► Column Intelligence Layer ──► Unified Metadata Report
File Branch ──────┘
```

The Column Intelligence Layer (PII tagging, key detection, description generation, semantic typing, knowledge graph indexing) is **completely reusable** across both branches — no duplication.

---

## What Is NOT Yet Implemented

The following components from this design spec do not yet exist in the codebase and will need to be built:

| Component                        | Status      |
|----------------------------------|-------------|
| File Intake Validator            | Not built   |
| File Type Classifier             | Not built   |
| Size Strategy Selector           | Not built   |
| CSV Profiling Engine             | Not built   |
| Parquet Profiling Engine         | Not built   |
| JSON Profiling Engine            | Not built   |
| Legacy Flat File Handler         | Not built   |
| Structural Quality Checker       | Not built   |
| Unified File Profile Writer      | Not built   |
| Multi-file partition support     | Not built   |
| Schema drift detection           | Not built   |
