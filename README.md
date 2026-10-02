# Numi Cancer Lab

Patient-specific longitudinal cancer research for the Numi suite.

## First implementation milestone

A local, runnable workflow: inspect a dated patient record, track measured lesions, freeze a forecast using only information available at a cutoff, reveal a later observation, and score the prediction against no-change and growth-extrapolation baselines.

The architecture separates measured observations, model predictions, and simulated hypotheses. It is designed for evidence exchange with Numi Human, NumiVivo, and Numi Lab, without claiming those integrations already exist.

## Research and data boundaries

- Research software, not a diagnostic device or treatment recommendation system.
- Public examples must be synthetic and explicitly labeled. No patient scans, reports, credentials, or private experiment artifacts belong in this repository.
- Real CancerVerse data remain local. The dataset is licensed separately under CC BY-NC-ND 4.0; commercial use requires reviewing the publisher's terms.
- Forecasting must not receive future scans, reports, annotations, or diagnosis-derived patient labels.
- Missing coverage is unknown, not zero tumor burden. Lesion identity across scans requires verified correspondence, not matching component numbers.
- A working software test is not evidence of clinical effectiveness.

## Primary sources

- Dataset and documented layout: https://huggingface.co/datasets/BodyMaps/CancerVerse
- Release and licensing information: https://www.thebodymaps.com/releases/

Implementation and test instructions will be committed with the executable increments.
