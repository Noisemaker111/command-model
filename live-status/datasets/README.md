# datasets

Built splits are private and live outside Git in `LIVE_STATUS_HOME/datasets/<version>/`
(default `<main checkout>/work/live-status/datasets/`). See [DATASET.md](../DATASET.md) for
the schema, split policy and measured distributions. Build code is in `dataset_build/`
(named so it cannot shadow the Hugging Face `datasets` package).
