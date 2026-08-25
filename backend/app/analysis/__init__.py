"""
Downstream AURA-X analysis stages (Phase 12): Repository Intelligence,
Evolution Analysis, Dependency Analysis, Risk Assessment, Test Planning.

Each module exposes one entry point, `analyze(context: RepositoryContext,
...) -> <Module>Report`, whose only required, repository-derived input is
`RepositoryContext` (Phase 3/8's normalized, provider-agnostic object) --
never a GitHub client, a filesystem re-scan, or a re-fetch of anything
already on `context`. See app/analysis/pipeline.py for the orchestrator
that runs all five against one context.

These modules are intentionally separate from app/services/ -- that
package is the GitHub *integration* boundary (URL parsing, the API
client, cloning, scanning, persistence); app/analysis/ is what consumes
its output, per the architecture diagram in
docs/GITHUB_INTEGRATION.md:

    RepositoryContext (normalized, provider-agnostic)
                     |
       +-------------+--------------------------------------+
       v             v                                       v
    Repository   Evolution / Risk / Test                 Reporting
    Intelligence     Planning                            (API / Dashboard / Excel)

Not yet wired into the ingestion job or exposed via the API -- that is
future work (see docs/GITHUB_INTEGRATION.md "Downstream analysis" for
current scope and what's deliberately deferred).
"""
