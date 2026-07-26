# Translation model selection

NLLB (`facebook/nllb-200-distilled-600M`) is the current default
general-purpose Russian-to-Chinese translation candidate. It produced relatively
natural results on the existing general lecture and operating-instruction
samples, runs within the measured local GPU budget, and works from the local
cache. This is a practical prototype choice, not a final model approval.

| Engine | Official model | Revision measured | License | Current role |
| --- | --- | --- | --- | --- |
| `nllb` | `facebook/nllb-200-distilled-600M` | `f8d333a098d19b4fd9a8b18f94170487ad3f821d` | CC-BY-NC-4.0 | Default general-purpose research candidate |
| `t5` | `utrobinmv/t5_translate_en_ru_zh_base_200` | `5a49c01acfa050e7f507dd89b5ef44bbf84edfd8` | Apache-2.0 | Retained experimental baseline |
| `m2m100` | `facebook/m2m100_418M` | `55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636` | MIT | Retained comparison candidate |

The three-model mathematical terminology benchmark is preserved unchanged as a
research record. Mathematical-domain optimization is not a core acceptance
requirement for this application and its old 85% threshold no longer blocks
general pipeline development. The results still show that none of these models
should be presented as specialized mathematical translation.

NLLB is CC-BY-NC-4.0 and its model card describes a research model rather than a
production deployment model. This project currently uses it only for learning,
research, and non-commercial work. Licensing, distribution, intended use, and
quality must be reviewed again before broader use. Users can still choose T5 or
M2M100 through the CLI.

The complete historical measurements and outputs are in
[`translation-model-comparison.md`](translation-model-comparison.md).

Official model pages:

- https://huggingface.co/facebook/nllb-200-distilled-600M
- https://huggingface.co/facebook/m2m100_418M
- https://huggingface.co/utrobinmv/t5_translate_en_ru_zh_base_200
