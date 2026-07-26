# Offline translation model comparison

## Scope and decision

This comparison uses the same 32 Russian-to-Simplified-Chinese samples for all
models. It measures automatic chrF, exact required-term hits, latency, throughput,
and peak CUDA allocation. chrF and term hits do not replace human review.

No model passes the internal candidate gate. All meet the GPU P95 limit of 0.7
seconds and the 4 GiB peak-memory limit, and all work from cache with networking
disabled. All fail the required 85% mathematical terminology accuracy and make
severe errors in mandatory concepts. Dedicated machine-translation models still
do not meet the project requirement. No model is selected, and translation must
not be connected to ASR.

## Models and local cache

| Engine | Official repository | Measured revision | License | Standard snapshot | Whole local cache |
| --- | --- | --- | --- | ---: | ---: |
| T5 | `utrobinmv/t5_translate_en_ru_zh_base_200` | `5a49c01acfa050e7f507dd89b5ef44bbf84edfd8` | Apache-2.0 | about 1.19 GB | 1,194,418,014 bytes |
| M2M100 | `facebook/m2m100_418M` | `55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636` | MIT | 1,941,931,012 bytes (1.809 GiB) | 3,877,615,381 bytes (3.611 GiB) |
| NLLB | `facebook/nllb-200-distilled-600M` | `f8d333a098d19b4fd9a8b18f94170487ad3f821d` | CC-BY-NC-4.0 | 2,482,646,304 bytes (2.312 GiB) | 4,943,003,911 bytes (4.604 GiB) |

M2M100 and NLLB are explicitly loaded from their official standard
`pytorch_model.bin` weights with `use_safetensors=False`. Before that setting was
added, Transformers fetched an automatic safetensors conversion snapshot; it was
not deleted, so the whole-cache figures include the standard snapshot, blobs, and
that extra snapshot under Windows degraded non-symlink caching.

NLLB is CC-BY-NC-4.0 and is only a research/academic project candidate. Its model
card says it is a research model and not released for production deployment.
Future distribution and every intended use must be reviewed against the license
again. M2M100 is MIT licensed. T5 remains an experimental baseline.

## Internal candidate gate

| Requirement | T5 | M2M100 | NLLB |
| --- | --- | --- | --- |
| GPU warm P95 <= 0.7 s | Pass | Pass | Pass |
| Peak CUDA <= 4 GiB | Pass | Pass | Pass |
| Mathematical terminology >= 85% | Fail: best 13.3% | Fail: best 8.9% | Fail: best 8.9% |
| Six mandatory terms have no severe error | Fail | Fail | Fail |
| General instructions have no clear reversal | Mostly pass | Mostly pass | Mostly pass |
| Fully offline verification | Pass | Pass | Pass |
| Overall candidate gate | **Fail** | **Fail** | **Fail** |

## GPU performance

Every row used 32 samples, two warmups per sample, three timed repetitions, a
separate Python process, CUDA float16, and standard non-safetensors weights for
the two Meta models.

| Engine | Beams | Tokenizer | Model | Cold total | Warm mean | Median | P95 | Source chars/s | chrF | Math chrF | Terms | Math terms | Peak CUDA |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| T5 | 1 | 5.659 s | 2.177 s | 7.837 s | 0.182 s | 0.175 s | 0.250 s | 320.33 | 25.914 | 16.046 | 19/64 (29.7%) | 4/45 (8.9%) | 659.3 MiB |
| T5 | 4 | 3.641 s | 1.901 s | 5.542 s | 0.212 s | 0.211 s | 0.290 s | 275.11 | 28.579 | 19.796 | 21/64 (32.8%) | 6/45 (13.3%) | 667.3 MiB |
| M2M100 | 1 | 4.821 s | 3.900 s | 8.721 s | 0.174 s | 0.121 s | 0.173 s | 335.07 | 19.568 | 14.095 | 14/64 (21.9%) | 4/45 (8.9%) | 949.2 MiB |
| M2M100 | 4 | 4.796 s | 7.023 s | 11.819 s | 0.146 s | 0.139 s | 0.208 s | 401.31 | 22.285 | 15.136 | 16/64 (25.0%) | 4/45 (8.9%) | 952.3 MiB |
| NLLB | 1 | 5.634 s | 5.299 s | 10.933 s | 0.156 s | 0.152 s | 0.216 s | 373.70 | 19.975 | 13.165 | 19/64 (29.7%) | 3/45 (6.7%) | 1190.3 MiB |
| NLLB | 4 | 5.514 s | 2.870 s | 8.384 s | 0.185 s | 0.169 s | 0.262 s | 316.39 | 23.214 | 15.839 | 20/64 (31.3%) | 4/45 (8.9%) | 1209.4 MiB |

## CPU performance

| Engine | Beams | Warmups | Repeat | Tokenizer | Model | Warm mean | Median | P95 | Source chars/s | chrF | Math chrF | Terms | Math terms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| M2M100 | 1 | 1 | 1 | 4.088 s | 3.398 s | 0.713 s | 0.489 s | 0.684 s | 81.98 | 19.568 | 14.095 | 14/64 (21.9%) | 4/45 (8.9%) |
| NLLB | 1 | 1 | 1 | 5.063 s | 2.008 s | 0.672 s | 0.623 s | 0.905 s | 86.98 | 19.975 | 13.165 | 19/64 (29.7%) | 3/45 (6.7%) |

## Per-category GPU results

| Configuration | Category | chrF | Required terms |
| --- | --- | ---: | ---: |
| T5 b1 | functional_analysis | 13.642 | 1/34 (2.9%) |
| T5 b1 | mathematics | 24.826 | 3/11 (27.3%) |
| T5 b1 | software | 61.268 | 9/11 (81.8%) |
| T5 b1 | general_lecture | 34.636 | 6/8 (75.0%) |
| T5 b4 | functional_analysis | 17.820 | 2/34 (5.9%) |
| T5 b4 | mathematics | 26.988 | 4/11 (36.4%) |
| T5 b4 | software | 61.062 | 9/11 (81.8%) |
| T5 b4 | general_lecture | 34.636 | 6/8 (75.0%) |
| M2M100 b1 | functional_analysis | 11.381 | 2/34 (5.9%) |
| M2M100 b1 | mathematics | 23.852 | 2/11 (18.2%) |
| M2M100 b1 | software | 36.635 | 6/11 (54.5%) |
| M2M100 b1 | general_lecture | 29.074 | 4/8 (50.0%) |
| M2M100 b4 | functional_analysis | 12.228 | 2/34 (5.9%) |
| M2M100 b4 | mathematics | 25.520 | 2/11 (18.2%) |
| M2M100 b4 | software | 42.150 | 7/11 (63.6%) |
| M2M100 b4 | general_lecture | 39.252 | 5/8 (62.5%) |
| NLLB b1 | functional_analysis | 11.673 | 1/34 (2.9%) |
| NLLB b1 | mathematics | 18.523 | 2/11 (18.2%) |
| NLLB b1 | software | 38.275 | 9/11 (81.8%) |
| NLLB b1 | general_lecture | 36.617 | 7/8 (87.5%) |
| NLLB b4 | functional_analysis | 15.288 | 2/34 (5.9%) |
| NLLB b4 | mathematics | 17.837 | 2/11 (18.2%) |
| NLLB b4 | software | 44.271 | 8/11 (72.7%) |
| NLLB b4 | general_lecture | 38.240 | 8/8 (100.0%) |

## Fully offline verification

Both `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` were set in one temporary
PowerShell session. Each model ran in its own process, loaded the standard cached
weights, and returned exit code zero. The variables were then removed.

| Engine | Output | Tokenizer | Model | Translation | Peak CUDA |
| --- | --- | ---: | ---: | ---: | ---: |
| M2M100 | `该模型运行本地,不会向互联网发送音频。` | 1.619 s | 1.174 s | 0.568 s | 938.0 MiB |
| NLLB | `模型是本地运行的,不会发送音频到互联网.` | 2.196 s | 2.343 s | 0.496 s | 1189.6 MiB |

## Actual outputs

The table records the beams=4 output for all 32 samples. The ignored local JSON
files also retain every beams=1 output and timing. References are Simplified
Chinese; model punctuation and Traditional characters are preserved as produced.

| # | Reference | T5 b4 | M2M100 b4 | NLLB b4 |
| ---: | --- | --- | --- | --- |
| 1 | 线性算子保持向量加法和标量乘法。 | 线性运算符保留矢量的叠加和乘以岩浆。 | 线性操作器保留 vector 组成和复制到岩石。 | 线性运算器保留了向量加和乘以 skalar. |
| 2 | 设 A 是巴拿赫空间上的有界线性算子。 | 让A - 在香蕉空间的有限线性运算符。 | 让 A 是一个有限的线性运营商在香蕉空间。 | 让A 在香空间中的有限线路运营商. |
| 3 | 完备的赋范空间称为巴拿赫空间。 | 完全正常的空间称为巴纳赫空间。 | 整個標準空間被稱為香蕉空間。 | 一个完整的规范空间被称为香空间. |
| 4 | 紧算子把有界序列映射为具有收敛子序列的序列。 | 紧凑型运算符将有限的序列转换为具有相近子序列的序列。 | 一个小型操作器将有限的序列转换为具有相匹配的序列。 | 紧操作器将有限的序列转化为相应的次序列. |
| 5 | 这个集合的闭包是紧的，因此该集合是预紧集合。 | 这个系列的结局是紧凑的,所以很多前缀都是紧凑的。 | 这个集合的关闭是紧凑的,所以许多是预紧凑的。 | 这个集合的关闭是紧的,所以这个集合是预紧的. |
| 6 | 线性泛函把每个向量映射为一个标量。 | 线性功能可对照每个矢量。 | 线性功能将每个维克特的岩石进行比较。 | 一个线性函数将每个向量进行相对较量. |
| 7 | 我们计算该泛函在单位球上的范数。 | 计算单个球上的函数规则。 | 我们将计算一个单球的功能标准。 | 我们可以在单个球上计算函数值. |
| 8 | 数 λ 是该算子的特征值。 | 兰巴数是操作员自己的值。 | 灯泡的数字是运营商的价值。 | 兰布达号是运算器本身的值. |
| 9 | 非零向量 x 称为特征向量。 | 非零矢量 x 称为自身的矢量。 | x 称为自己的 vector。 | 不为零的向量x被称为自己的向量. |
| 10 | 范数收敛蕴含弱收敛。 | 正常的相似性是微弱的相似性。 | 相似性通常会导致弱相似性。 | 通常的相似性会导致较弱的相似性. |
| 11 | 这个序列是柯西序列。 | 这种一致性是基本的一致性。 | 这种连续性是基本的连续性。 | 这个序列是基本的序列. |
| 12 | 集合的测度等于其互不相交部分测度之和。 | 倍数等于不可分割部分的总和。 | 多元的尺寸相当于不可分割的部分的尺寸。 | 集合的尺寸等于不可交叉的部分的尺寸的总和. |
| 13 | 可测函数是简单函数序列的极限。 | 可测量函数是简单函数序列的极限。 | 可测量的函数是简单函数序列的边界。 | 测量函数是简单函数连续的边界. |
| 14 | 勒贝格积分可定义在非负可测函数上。 | Lebeg 是为非负可测量函数而定义的。 | 利贝格集成为不可否认的可测量的功能。 | 莱贝格的整体是为不可否定的测量函数而定义的. |
| 15 | 两个函数关于该测度几乎处处相等。 | 这两个功能几乎在任何地方都是相同的。 | 这两种功能几乎在任何地方都是一样的。 | 这两个函数几乎在任何地方都相同. |
| 16 | 共轭算子作用在对偶空间上。 | 串联的操作员在双重空间中工作。 | 压缩操作器在双空间中运作。 | 连接操作器在双重空间中运行. |
| 17 | 如果原算子是双射，则逆算子存在。 | 如果原始运算符是生物的,则存在反向运算符。 | 返回运营商存在,如果起源运营商是双向的。 | 如果原始运算符是双向的,反向运算符就会存在. |
| 18 | 闭算子具有闭图像。 | 闭路操作员有一个封闭的时间表。 | 关闭的运营商有一个关闭的日程表。 | 封闭的操作员有封闭的时间表. |
| 19 | 我们用数学归纳法证明该定理。 | 用数学诱导法来证明定理。 | 让我们用数学引导方法证明理论。 | 通过数学引入方法来证明该理论. |
| 20 | 函数在该点的导数等于零。 | 在此点的衍生函数为零。 | 在这个点上,产能函数相当于零。 | 这一点的产量函数是零. |
| 21 | 矩阵的行列式不等于零。 | 矩阵定义符不等于零。 | 矩阵的定义不等于零。 | 矩阵的定义器不等于零. |
| 22 | 连续函数在闭区间上达到最大值。 | 连续函数在段内达到最大值。 | 连续的功能在切割中达到最高水平。 | 不断的功能在切片中达到最大水平. |
| 23 | 内积确定向量的长度。 | 染色体决定了矢量的长度。 | 岩石作品决定了 vector 的长度。 | 尺度分数决定了向量的长度. |
| 24 | 希尔伯特空间是完备的内积空间。 | 吉尔伯特的空间是一个完整的空间与岩石作品。 | 希尔伯特空间是一个充满岩石作品的空间。 | 吉尔伯特的空间是一个完整的空间, |
| 25 | 首先启动程序，然后在设置中选择麦克风。 | 首先启动程序,然后在设置中选择麦克风。 | 首先启动程序,然后在设置中选择麦克风。 | 首先启动程序,然后在设置中选择麦克风. |
| 26 | 模型在本地运行，不会将音频发送到互联网。 | 该模型在本地运行,不会将音频发送到互联网。 | 该模型运行本地,不会向互联网发送音频。 | 该模型是本地运行的,并且不会将音频发送到互联网. |
| 27 | 如果出现错误，请检查设备连接并重试。 | 如果出现错误,请检查设备连接并重复尝试。 | 如果出现错误,请检查设备连接并重复尝试。 | 如果出现错误,请检查设备的连接,然后再试一次. |
| 28 | 下载后模型保存在缓存中，并可在无网络时运行。 | 加载后,该模型保存在缓存中,可以在没有互联网的情况下工作。 | 在下载后,该模型存储在现金中,并且可以在没有互联网的情况下运行。 | 在下载后,模型存储在缓存中,并且可以在没有互联网的情况下工作. |
| 29 | 我们来看下一张幻灯片。 | 让我们进入下一个幻灯片。 | 让我们转到下一个幻灯片。 | 让我们转到下一个幻灯片. |
| 30 | 定理2.3将在休息后证明。 | 理论2.3在中断后得到证实。 | 理論 2.3 將在休息後被證明。 | 我们将在休息后证明2.3定理. |
| 31 | 当 t = 0 时，参数值为零。 | 参数值为零,t = 0。 | 参数值为 0 与 t = 0 等。 | 在 t = 0 时,参数值等于零. |
| 32 | 讲座结束时，教师将回答学生的问题。 | 讲座结束时,老师会回答学生的问题。 | 讲座结束后,教师将回答学生的问题。 | 在讲座结束时,教师会回答学生的问题. |

## Human review: severe errors

- **T5:** `scalar` becomes “magma”; Banach space becomes “banana space”;
  functional/norm terminology becomes generic “function/rule”; eigenvalue and
  eigenvector are lost; inverse-operator bijectivity becomes “biological”;
  closed graph becomes a timetable; inner product becomes “chromosome”.
- **M2M100:** leaves Russian/English fragments; translates scalar as “rock”;
  bounded linear operator as a limited telecom operator; eigenvalue as lottery
  or lamp value; one beams=1 adjoint-operator output is empty; inverse/closed
  operators become telecom/return concepts; derivative becomes production;
  inner product becomes “rock work”; cache becomes cash.
- **NLLB:** leaves `skalar`; loses Banach space and bounded linear operator;
  confuses sequence with continuity, measure with size, and norm with standard;
  loses eigenvalue/eigenvector, adjoint/inverse/closed operator, Lebesgue integral,
  derivative, determinant, and inner product; one Hilbert-space sentence is
  incomplete.

General software instructions are much better than mathematics for all models,
but that does not compensate for systematic domain failures. Selection cannot be
based on chrF alone.

## Reproducibility and warnings

- Python 3.11.9; Torch 2.12.1+cu130; CUDA runtime 13.0; RTX 4060 Laptop GPU.
- Model processes and benchmark configurations were strictly sequential.
- The Windows Hugging Face cache cannot use symlinks and consumes extra space.
- An earlier M2M100 `vocab.json` download timed out once and resumed successfully.
- Transformers warns that both a model `max_length` and CLI `max_new_tokens` are
  present; `max_new_tokens` takes precedence. Generation remains deterministic
  with `do_sample=False`.
- Local benchmark JSON/log files remain under ignored `data/` and are not part of Git.

Official sources:

- https://huggingface.co/utrobinmv/t5_translate_en_ru_zh_base_200
- https://huggingface.co/facebook/m2m100_418M
- https://huggingface.co/facebook/nllb-200-distilled-600M
