# Grid Pulse

GB electricity data platform: half-hourly carbon intensity (batch) and Elexon market data (streaming via IRIS), landed in ClickHouse and modelled with dbt.

> Work in progress. Architecture, design decisions and trade-offs will be documented here as each phase lands.

## Quick start (local)

```bash
cp .env.example .env        # fill in values
docker compose up -d
curl "http://localhost:8123/?user=grid&password=grid" --data "SELECT version()"
```
