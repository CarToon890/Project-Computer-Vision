# OMR from Smartphone Photos

[ภาษาไทย](README.md) | English

This project reads marks on 100-question answer sheets photographed with a phone, reducing manual marking work. It compares a CLA-style bubble-fill method with a CNN and helps users review uncertain answers before scoring.

## Try it

- **Web demo:** [Open the OMR demo](https://omr-project-demo.vercel.app), select the generated sample image, read and review the answers, and try exporting CSV. See the [demo guide](DEMO_RUNBOOK.md) for steps and limitations. Availability and quotas may change.
- **Local Windows app:** Read the [application guide](APP_RUNBOOK.md) before running `start_omr.cmd`. The launcher needs a local Python runtime, dependencies, model weights, and form reference data that are not included in Git; cloning alone is not enough for real-image inference.
- **Development:** See [CONTRIBUTING.md](CONTRIBUTING.md) for dependencies and test commands.

## How it works

1. Provide image A and optionally image B of the same sheet.
2. Align the form and read the marks with CLA and CNN.
3. Review suggested answers and flagged questions; confirm or correct them.
4. Select an answer key, calculate a score, and export results with model output distinguished from human review.

Model answers are suggestions. Unflagged answers can also be wrong; review and confirm every answer before using a score for an exam decision.

## Data and evaluation limits

Original answer-sheet photos and model weights are excluded from Git. The repository **does contain** answer labels, contributor information, and review artifacts in the [39-sheet test dataset](data/dataset_v2_test39/README.md). It includes sheets already used in evaluation and answers accepted in bulk from model drafts, so it is not an independent test set. Bulk acceptance does not establish that each mark was checked against its image.

Development-set figures and synthetic-image results do not establish independent accuracy on new photographs. See the [independent evaluation protocol](INDEPENDENT_EVALUATION_PROTOCOL.md) and [v3 training results](V3_TRAINING_RESULTS.md) for context and limitations.

## Documentation

The [documentation index](DOCUMENTATION.md) links to usage, development, data, model, and experiment guides. Existing reports remain at their original paths.
