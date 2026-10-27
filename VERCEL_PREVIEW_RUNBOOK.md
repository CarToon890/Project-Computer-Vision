# OMR private cloud Preview

## Scope and cost boundary

- Use only Vercel Hobby and Neon `free_v3`. Do not enable a paid plan, paid trial,
  paid build machine, billing upgrade, or automatic paid overage.
- Engine project: `omr-cnn-engine` (`prj_aXd6kY85PTm2Y9crMCTprfTja2kB`).
- Team: `team_zYK3JQ8mj7CZKXONoTxcbMJH`.
- Private Blob: `omr-private` (`store_MQi5AZf8pYGqgQ8N`), iad1.
- Database: `omr-db` (`store_6LnwdMH0P5eJbUaY`), Neon Free, iad1.
- Resources are linked to Preview/Development only. Production is not ready.
- Dataset photographs and ground-truth labels are excluded from deployment source.
  Explicit parity fixtures are uploaded privately as test jobs, never as public demos.

## Engine deployment

Use the pinned CLI installed locally, not `npm exec`: this Windows environment
has forwarded/swallowed some CLI flags through `npm exec`.

Use `--environment preview` explicitly. CLI 65.4.0 deprecated `--target`, and an
initial attempt with that flag selected Production and failed the 500 MB size
limit; it did not publish a working Production application.

The engine uses Python 3.13 and `uv.lock`, CPU-only PyTorch, and Large Functions.
Preview has `VERCEL_SUPPORT_LARGE_FUNCTIONS=1` and maxDuration 180 seconds.
The actual Preview build accepted the large-functions beta on this account.

`tools/package_vercel_engine.py` stages source separately from private system
artifacts. `tools/setup_engine_env.mjs` configures Preview-only signing and model
manifest settings, applies the additive SQL schema, and uploads immutable v3
artifacts with checksum verification. Secrets travel via environment/stdin.
Never print or commit `.env.local`, `.vercel`, private fixtures, or model weights.

`GET /health` reports configuration presence only; it does not prove successful
inference. `POST /infer` requires a short-lived HMAC signature and existing job
and attempt IDs. It accepts no arbitrary image URLs. The engine loads private
files, checks v3 hashes, reads at most one job at a time through a database lease,
reserves storage before writing artifacts, and persists results before returning.

Private Blob can omit Content-Length. `PrivateBlobStore.read` checks a declared
size when available and always counts streamed bytes. The first real Preview
request exposed this behavior; the fix has a regression test.

## Verification

`tests/test_cloud_engine.py` covers HTTP signatures, invalid input, ownership of
source paths, duplicate requests, storage ordering, quotas, failures, local
concurrency, image bounds, and chunked private downloads without a size.

`tools/verify_vercel_engine.py` uses the existing linked credentials, private
test uploads, and `vercel curl` to retain Deployment Protection. It compares
S0035/S0106 A-only and A+B with saved Windows decisions, including CNN/CLA,
review flags, B selection, and pair checks. It tests forged signatures and repeat
requests. Reports and images stay under ignored `presentation_build/`.

This is functional consistency testing, not independent accuracy evaluation.
Cloud answers are drafts and do not update canonical dataset labels.

## Remaining release gates

The Next.js user application, owner password login, upload authorization, image
expiry access checks, cleanup endpoint, review revisions, scoring and export are
implemented. Localhost-to-Vercel smoke and resilience checks passed; see
`CLOUD_PREVIEW_RESULTS.md`. The owner must set their own password through
`OWNER_SETUP.md` before Preview login and the complete online web flow can pass.
Actual mobile-camera testing and Production release remain pending.
An engine Preview URL alone is not a finished user website.

All test source/derived blob records have the original job's seven-day expiry.
Daily deletion is not active until Production's cleanup endpoint and cron are configured;
do not claim automatic cleanup is already running. System model files have no
image expiry and must never be removed by image cleanup.
