# CNN v3 cloud feasibility probe

This is an isolated CLI experiment for Linux packaging and inference parity.
It is not the online application, an authenticated API, or a Vercel deployment.
The existing local application continues using its original dataset references
unless `data/metadata/form_references.npz` is explicitly supplied in its root.

## Build locally

Use the project's existing Python runtime and model/CV dependencies:

```powershell
python tools/package_cloud_probe.py --output presentation_build/cloud_probe_bundle
docker build --tag omr-v3-cloud-probe:matched-20261028 presentation_build/cloud_probe_bundle
python tools/verify_cloud_probe.py --output presentation_build/cloud_probe_comparison
```

Choose a new output directory for each run; existing output is preserved.
The package contains the unchanged v3 weights/config, inference code, and
precomputed registration features. It excludes dataset photographs, answer
labels, image inventories, splits, and development reports. Reference features
are still private derived data; this package is not a public demo asset.

The test mounts local copies of S0035 and S0106 A/B read-only into a container,
with networking disabled and a 2 GiB / 1 CPU limit. It compares CNN and CLA
answers, review decisions, B usage, confidence deltas, and the pair gate between
the current Windows runtime and the pinned Linux experiment runtime.
Results are functional comparisons on development images, not independent
accuracy, new labels, or a claim of performance on Vercel.

## Version boundary

The Docker requirements match the direct package versions in the current
Windows runtime (including the OpenCV distribution build number). An initial
experiment with older dependencies changed one CLA decision and is preserved
in the local experiment history. Matching versions still requires comparing
actual outputs across operating systems. Freeze a complete reviewed dependency
lock for the chosen hosting runtime before release.

## Still required before online deployment

- Export a compatible HTTP/ASGI/WSGI entrypoint instead of starting the local server.
- Persist jobs, reviews and scores outside instance memory/local disk.
- Authorize direct private uploads rather than proxying large Base64 payloads.
- Add identity, job ownership, developer access control and upload quotas.
- Make HEIC conversion work on Linux and test actual mobile camera uploads.
- Verify Vercel bundle/runtime eligibility, cold-start behavior and billing.
- Provision a dedicated OMR project; do not overwrite unrelated Vercel projects.

Deploying only `web/` will display the interface but does not supply the CNN API.
