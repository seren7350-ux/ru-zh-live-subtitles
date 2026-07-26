# Translation model selection

This spike evaluates only `utrobinmv/t5_translate_en_ru_zh_base_200`. The other
models are documented candidates and are not downloaded or benchmarked here.
No untested model is claimed to have the best translation quality.

| Model | Direct ru→zh | Parameters | Published repository size | License | CPU/GPU | Expected latency | Tested here |
| --- | --- | ---: | ---: | --- | --- | --- | --- |
| `utrobinmv/t5_translate_en_ru_zh_base_200` | Yes | about 0.3B | about 1.19 GB | Apache-2.0 | PyTorch CPU/CUDA | Measured 0.184 s GPU warm mean at beams=1 and 0.279 s CPU warm mean; terminology quality is weak | Yes |
| `facebook/m2m100_418M` | Yes | 418M | about 3.88 GB total; PyTorch weights about 1.94 GB | MIT | PyTorch CPU/CUDA | Expected to be slower and larger than the selected T5 model; not measured | No |
| `facebook/nllb-200-distilled-600M` | Yes | 600M | about 2.48 GB | CC-BY-NC-4.0 | PyTorch CPU/CUDA | Expected to be the heaviest of these three; not measured | No |

## Decision

The T5 checkpoint is selected because it directly supports Russian, Chinese,
and English; uses the permissive Apache-2.0 license; exposes standard T5 files
without requiring remote custom code; and is the smallest candidate in this
comparison. Its domain quality and suitability for real-time subtitles must be
determined from the measured corpus and human review, not model size alone.

M2M100 is a permissively licensed MIT fallback candidate for later measurement.
NLLB is deferred: its CC-BY-NC-4.0 terms must be reviewed again before future
distribution or commercial use, and the model card describes it as a research
model rather than a production deployment model.

Sources:

- https://huggingface.co/utrobinmv/t5_translate_en_ru_zh_base_200
- https://huggingface.co/facebook/m2m100_418M
- https://huggingface.co/facebook/nllb-200-distilled-600M
