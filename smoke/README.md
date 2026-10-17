# 100-company smoke test

`companies.jsonl` holds 100 organisation numbers drawn at random from the public Signalpost universe. The run used the command in the main README:

```bash
uv run --frozen varde run --organisations smoke/companies.jsonl --output smoke/envelopes.jsonl \
  --report smoke/run-report.json --run-id smoke-v3 --expected-count 100 --state-dir smoke/state
```

| File | Contents |
|---|---|
| `envelopes.jsonl` | One terminal envelope per company |
| `profiles.jsonl` | The same facts flattened |
| `run-report.json` | Runtime, requests by host, coverage by field family, contract checks |
| `report.html` | Open in a browser to search, compare and verify every fact (keep it next to `snapshots/`) |
| `snapshots/` | The saved responses behind every claim, named by SHA-256 |
| `rerun/` | A second run against the first (`--previous smoke/envelopes.jsonl`): zero changes, which shows refresh is idempotent |
