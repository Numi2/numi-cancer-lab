# Development contract

Build the patient-specific cancer research workflow. Reuse the canonical Patient, Snapshot and ExperimentSpec records; do not add a second patient database or a separate service without a demonstrated need.

## Budget and verification

The owner has explicitly prohibited hosted CI expenditure. Do not create or restore GitHub Actions workflows, scheduled jobs, hosted CI integrations, paid runners, or automatic cloud deployments. Do not dispatch or rerun remote jobs. Keep regression tests and browser checks local. Do not remove tests to save CI costs. A change to this policy requires explicit owner approval.

Before changes, inspect current main and the worktree. Preserve unrelated work. Never force-push. Publish tested, coherent increments when authorized; distinguish tested local code from published code. Report skipped tests and unavailable dependencies honestly.

Run `python -m pytest -q` and the local synthetic benchmark. Run the local browser smoke test when its dependencies are available. No remote job is a substitute for local verification.

## Research boundaries

Forecasters receive only Snapshot, never full Patient. Preserve acquisition and availability dates. Exclude future scans, reports and retrospectively assigned labels from earlier model inputs. Freeze predictions before evaluation. Missing coverage is unknown. Unreviewed scan components are not persistent lesions. Include new lesions in complete organ-burden scoring.

Never publish patient scans, reports, identifiers, experiment artifacts, credentials or downloaded datasets. Label synthetic fixtures. Preserve source licenses. No automatic multi-terabyte downloads. Keep the unauthenticated research server loopback-only.

Do not describe numerical baselines as trained AI, equal-volume spheres as anatomy, simulations as observations, or software tests as clinical validation. Native Numi integration requires a real consuming-repository end-to-end test. Treatment simulations require intervention-specific evidence; do not expose them as treatment recommendations.
