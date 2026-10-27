# Perspective correction profile

Uses the exact CNN weights from `models/retrained_v2/`, SHA256
`aa8a4c260b9ebc86ba6ce8159ee95e6891a9ca7a29cc7198e3afc79662da1a82`.
CNN cutoff and CLA fill/margin thresholds are frozen at v2 values.
No new training or automatic promotion of draft labels took place.

Shared preprocessing now warps source pixels to the answer plane before both
readers, with per-row straightening for residual page curvature.
The local web app prefers this profile automatically.

See `PERSPECTIVE_FIX.md` and
`presentation_build/system_test_270_perspective_fixed/summary.json`.
540 images registered successfully; this does not imply all answers are correct.
The historical 1,000-question cohort is an assisted development retest.
Current CNN: A-only 998 correct, 2 deferred; A-then-B 999 correct, 1 wrong.
Current CLA: A-only 948 correct; A-then-B 987 correct.
The experimental recalibration profile was retained as evidence but not deployed.
