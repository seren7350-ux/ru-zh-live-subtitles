# Translation model selection

This spike evaluates `utrobinmv/t5_translate_en_ru_zh_base_200` only as an
experimental baseline and provisional benchmark model. It is not approved for
final subtitle use. The other models are documented comparison candidates and
are not downloaded or benchmarked in this spike. No model is currently selected
as the final default translation model.

| Model | Direct ru→zh | Parameters | Published repository size | License | CPU/GPU | Expected latency | Tested here |
| --- | --- | ---: | ---: | --- | --- | --- | --- |
| `utrobinmv/t5_translate_en_ru_zh_base_200` | Yes | about 0.3B | about 1.19 GB | Apache-2.0 | PyTorch CPU/CUDA | Measured 0.184 s GPU warm mean at beams=1 and 0.279 s CPU warm mean; terminology quality is weak | Yes |
| `facebook/m2m100_418M` | Yes | 418M | about 3.88 GB total; PyTorch weights about 1.94 GB | MIT | PyTorch CPU/CUDA | Expected to be slower and larger than the T5 experimental baseline; not measured | No |
| `facebook/nllb-200-distilled-600M` | Yes | 600M | about 2.48 GB | CC-BY-NC-4.0 | PyTorch CPU/CUDA | Expected to be the heaviest of these three; not measured | No |

## Current conclusion

The T5 checkpoint was useful as an experimental baseline because it directly
supports Russian, Chinese, and English; uses the permissive Apache-2.0 license;
exposes standard T5 files without requiring remote custom code; and is the
smallest candidate in this comparison. Its measured speed and GPU memory usage
meet the prototype target, and general software instructions are often usable.
However, the recorded outputs contain severe mathematical terminology errors,
including mistranslations of linear operator, Banach space, and functional norm.
It must not be used for unattended mathematical classroom subtitles.

There is no final default translation model. The next stage compares this T5
baseline against M2M100 and NLLB using the same corpus, terminology checks, and
CPU/GPU measurements. ASR and translation remain separate until a candidate
meets the project's quality threshold. M2M100 is MIT licensed. NLLB is subject
to CC-BY-NC-4.0 restrictions that must be reviewed again before distribution or
commercial use.

Sources:

- https://huggingface.co/utrobinmv/t5_translate_en_ru_zh_base_200
- https://huggingface.co/facebook/m2m100_418M
- https://huggingface.co/facebook/nllb-200-distilled-600M
