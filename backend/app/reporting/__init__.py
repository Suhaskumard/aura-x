"""
Reporting (Phase 14): routes repository facts into Excel workbooks.

Per the architecture diagram in docs/GITHUB_INTEGRATION.md, "Reporting"
(API / Dashboard / Excel) is a consumer of persisted repository state,
parallel to app/analysis/ (Evolution / Risk / Test Planning). This
package is the Excel half -- app/api/v1/ is the API half (Phase 10),
frontend/ is the dashboard half (Phase 13).
"""
