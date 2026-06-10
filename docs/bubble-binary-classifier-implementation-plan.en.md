# Bubble Binary Classifier Implementation Plan

## Goal

Build a binary classifier that takes a single OMR bubble crop image and predicts whether the bubble is actually marked as `filled` or `not-filled`.

The initial scope is limited to answer bubbles (`kind=problem`).

## Current Status

The following pieces are already prepared.

- Label Studio export JSON has been collected.
- A manifest CSV has been generated for `problem` bubbles only.
- The mapping between `data.scan` image paths and human labels has been verified.
- The referenced S3 objects have been confirmed to exist.
- Sample images have been downloaded and visually confirmed to be bubble crops.
- Sample size distribution has been checked.
  - The currently inspected `problem` crops are fixed at `31x54`.

Relevant files:

- export JSON: [project-2-at-2026-05-17-15-02-b24adaa3.json](/abs/path/C:/dev/QMR/project-2-at-2026-05-17-15-02-b24adaa3.json)
- full manifest: [training/manifests/project-2-all.csv](/abs/path/C:/dev/QMR/training/manifests/project-2-all.csv)
- problem-only manifest: [training/manifests/project-2-problem.csv](/abs/path/C:/dev/QMR/training/manifests/project-2-problem.csv)
- export converter: [training/src/export_labelstudio_dataset.py](/abs/path/C:/dev/QMR/training/src/export_labelstudio_dataset.py)

## Problem Definition

Each sample is one bubble.

- Input: one `scan` bubble crop image
- Output: `filled` or `not-filled`

In the first baseline, the `template` image will not be used as a model input. It remains in the manifest for future experiments.

## Dataset Scope

The first round of experiments uses `kind=problem` only.

Reasons:

- Answer bubble classification is the primary product goal.
- `identifier`, `metadata`, and `option` bubbles may follow different visual distributions and usage patterns.
- A narrower scope makes the baseline easier to interpret.

Later experiments can compare:

- a `problem`-only model
- a model trained on all kinds

If all kinds are used later, `problem` performance must still be reported separately.

## Dataset Structure

The current manifest includes:

- `image_uri`
- `template_uri`
- `label`
- `request_id`
- `job_id`
- `area_id`
- `area_index`
- `local_id`
- `kind`
- `worker_verdict`
- `fill_ratio`
- `delta_fill_ratio`
- `baseline_fill_ratio`

For the initial baseline, the minimum required columns are:

- `image_uri`
- `label`

The remaining fields should be preserved for traceability and error analysis.

## Split Strategy

Do not use a random row-level split.

If bubbles from the same uploaded OMR sheet appear across train/val/test, the evaluation can leak information and overestimate real-world performance.

Use a grouped split by `request_id`.

Recommended ratio:

- train: 80%
- val: 10%
- test: 10%

Store split outputs as separate manifest files, for example:

- `training/manifests/project-2-problem-train.csv`
- `training/manifests/project-2-problem-val.csv`
- `training/manifests/project-2-problem-test.csv`

## Image Access Strategy

For the initial baseline, download the required S3 images into a local cache before training.

Reasons:

- simpler implementation
- no network I/O inside the DataLoader
- easier restart/recovery flow on a spot instance

Recommended approach:

- keep manifests in terms of S3 URIs
- download the required images into a local cache directory before training
- optionally preserve `request_id/job_id` structure in the local cache

## Model Strategy

Train two models separately and compare them.

Models:

1. `ResNet18`
2. `ConvNeXt-Tiny`

These are not intended as an ensemble in the first phase. They are independent experiments run on the same dataset and split.

Reasons:

- `ResNet18` is a simple, stable baseline.
- `ConvNeXt-Tiny` is a more modern CNN backbone.
- A comparison is needed to decide whether the more complex model is actually justified for this task.

## Model Loading

The model is not loaded from AWS itself. AWS only provides the GPU machine.

The training code will load model architectures and pretrained weights from `torchvision`, such as:

- `torchvision.models.resnet18`
- `torchvision.models.convnext_tiny`

Use pretrained ImageNet weights and replace the final classification head with a 2-class head.

## Input Preprocessing

The current crop size is `31x54`.

A resize step is required for standard CNN backbones.

Initial proposal:

- load grayscale image
- convert to RGB or replicate into 3 channels
- resize to `224x224`
- apply standard normalization

Keep augmentation minimal until the baseline results are available.

## Metrics

Do not rely on accuracy alone.

Track:

- precision
- recall
- F1

In particular, prioritize recall for the `filled` class.

Reason:

- missing truly marked bubbles is operationally costly

## Threshold Strategy

The model should output a probability for `filled`.

Start with a decision threshold of `0.5`.

Then sweep the threshold on the validation set if a different operating point gives better tradeoffs.

Treat the threshold as a configuration value separate from the model weights.

## Implementation Order

1. write a grouped split script by `request_id`
2. generate train/val/test manifests
3. write a local image cache/download script
4. implement PyTorch `Dataset` and `DataLoader`
5. implement `ResNet18` baseline training
6. implement `ConvNeXt-Tiny` baseline training
7. implement validation/test evaluation
8. compare results and tune threshold

## Execution Environment

Run experiments on the Dev Spot GPU Instance.

Access method:

- SSM

Operating rules:

- save checkpoints frequently
- back up manifests and outputs to S3
- avoid overly long single runs
- keep experiments restartable

## S3 Backup Policy

Because the training machine is a spot instance, upload the following artifacts to S3 regularly:

- train/val/test manifests
- training config files
- checkpoints
- best model
- metric summaries
- evaluation outputs

## Future Extensions

After the baseline:

- include non-`problem` kinds
- use the `template` image
- combine worker metrics such as `fill_ratio` and `delta_fill_ratio`
- operate a review flow for low-confidence samples
- integrate the classifier into the worker inference path

## Completion Criteria

The first implementation phase is considered complete when:

- `problem` data has been split into train/val/test
- `ResNet18` baseline training runs successfully
- `ConvNeXt-Tiny` baseline training runs successfully
- the two models can be compared on val/test
- the training flow is reproducible and backed up to S3
