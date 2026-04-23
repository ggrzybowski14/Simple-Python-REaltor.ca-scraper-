# CREA HPI Pipeline

This project now supports a source-aware CREA MLS HPI appreciation pipeline for market pages.

## What It Uses

- file type: `Seasonally Adjusted (M).xlsx`
- source key: `crea_hpi`
- canonical calculation input: `index_value`
- UI-friendly display input: `benchmark_price`

The parser was built after inspecting the real CREA monthly workbook structure:

- one worksheet per market or geography
- row 1 is the header row
- `Date` is stored as an Excel serial date
- each property type has paired index and benchmark columns

## Tables

### `hpi_observations`

Raw normalized monthly HPI rows.

One row per:

- source
- market
- property type
- month
- seasonal adjustment mode

### `hpi_market_metrics`

Precomputed website-facing appreciation metrics by:

- source
- market
- property type

Current metrics include:

- latest benchmark price
- 1M change
- 3M change
- 12M change
- 5Y total appreciation
- 5Y CAGR
- 10Y total appreciation
- 10Y CAGR
- trend direction
- data quality flag

## How To Run

Import raw CREA observations from a local folder:

```bash
python3 scripts/import_crea_hpi.py "/path/to/crea/folder"
```

Calculate derived metrics and publish source-specific market series:

```bash
python3 scripts/update_hpi_market_metrics.py
```

Dry run either step with `--dry-run`.

## How The Website Uses It

The market page now resolves appreciation like this:

1. look for `hpi_market_metrics` for the market and property type
2. if found, use the source-specific CREA series in `market_metric_series`
3. if not found, fall back to the existing non-CREA appreciation series
4. if nothing exists, show the explicit empty state

Current market-page default property type is `composite`.

## Mapping Notes

The importer maps CREA worksheet names into repo market keys.

Important current overrides:

- `VICTORIA` -> `victoria_bc`
- `GREATER_VANCOUVER` -> `vancouver_bc`
- `AGGREGATE` -> `canada`

If CREA workbook names change, update the mapping logic in [crea_hpi.py](/Users/georgia/Projects/simple realtor.ca scraper python/crea_hpi.py:1).

## Calculation Rules

Calculations use `index_value`, not benchmark price.

- total appreciation: `(latest / historical) - 1`
- CAGR: `(latest / historical)^(1 / years) - 1`
- 12M change: `(latest / 12M ago) - 1`
- 1M change: `(latest / prior month) - 1`

If an exact monthly point is missing, the calculator uses the closest valid observation within a tolerance and records that decision in `method_notes`.

## Data Quality

- `high`: enough clean data for 10Y, 5Y, 12M, and 1M
- `medium`: enough for 5Y and 12M but not 10Y
- `low`: incomplete or unstable history

## Future Extension

The pipeline is source-aware so another appreciation source can be added later for smaller markets without changing the market-page contract.
