# Translation model selection

There is no approved final translation model. T5 is the experimental baseline;
M2M100 and NLLB were measured as independent comparison candidates. All three
support direct Russian-to-Chinese translation, but none reaches the internal
mathematical terminology requirement.

| Engine | Official model | Revision measured | License | Role | Result |
| --- | --- | --- | --- | --- | --- |
| `t5` | `utrobinmv/t5_translate_en_ru_zh_base_200` | `5a49c01acfa050e7f507dd89b5ef44bbf84edfd8` | Apache-2.0 | Experimental baseline | Not approved; best math terminology accuracy 13.3% |
| `m2m100` | `facebook/m2m100_418M` | `55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636` | MIT | Comparison candidate | Not approved; best math terminology accuracy 8.9% |
| `nllb` | `facebook/nllb-200-distilled-600M` | `f8d333a098d19b4fd9a8b18f94170487ad3f821d` | CC-BY-NC-4.0 | Research/academic comparison candidate | Not approved; best math terminology accuracy 8.9% |

GPU latency and memory are not the blockers: all six GPU configurations stayed
below the internal 0.7-second P95 and 4 GiB peak-memory limits. Quality is the
blocker. The models mistranslate or omit core concepts including linear operator,
bounded linear operator, Banach space, compact operator, functional, and norm.
No model may be connected to ASR or used for unattended mathematical classroom
subtitles.

M2M100 is MIT licensed. NLLB is CC-BY-NC-4.0 and its model card describes a
research model rather than a production deployment model; future distribution,
commercial use, and general use scope must be reviewed again. The complete
measurements and outputs are in
[`translation-model-comparison.md`](translation-model-comparison.md).

Sources:

- https://huggingface.co/utrobinmv/t5_translate_en_ru_zh_base_200
- https://huggingface.co/facebook/m2m100_418M
- https://huggingface.co/facebook/nllb-200-distilled-600M
