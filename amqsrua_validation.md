## amqsrua Side-by-Side Validation

Use the local runner to compare IBM's sample utility with the exporter:

```powershell
.\run_amqsrua_validation.ps1
```

or:

```cmd
run_amqsrua_validation.bat
```

Optional arguments:

```powershell
.\run_amqsrua_validation.ps1 -QueueManager QM1 -ExporterBaseUrl http://localhost:9157 -PublicationCount 1
.\run_amqsrua_validation.ps1 -AmqsruaPath "C:\Program Files\IBM\MQ\tools\c\Samples\Bin64\amqsrua.exe"
```

What it does:

- queries `/status`
- queries `/metrics` and prints a short summary
- locates `amqsrua.exe` from `-AmqsruaPath`, `PATH`, or `MQ_INSTALLATION_PATH`
- runs a few deterministic `amqsrua` checks:
  - `CPU / QMgrSummary`
  - `DISK / Log`
  - `STATMQI / PUT`

If `amqsrua.exe` is not installed, the script prints a checklist instead of failing.

Recommended interpretation:

- if the exporter reports `ibmmq_system_topic_messages_consumed 0` and `amqsrua` also fails to produce publications, the limitation is likely queue-manager-side behavior rather than exporter parsing
- if `amqsrua` receives publications but the exporter does not, the remaining gap is in the exporter's metadata discovery or topic subscription logic
