// Fixed, complete mock text. These fixtures never enter SubtitleCard itself.
export const subtitleSamples = [
  {
    id: "short",
    label: "双语短句",
    chineseText: "我们明天会继续讨论这个问题。",
    russianText: "Мы продолжим обсуждать этот вопрос завтра.",
  },
  {
    id: "long",
    label: "超长双语字幕",
    chineseText: "如果你对这个结论还有疑问，我们可以在下节课继续详细讨论，并通过更多例子来说明每一步推理，直到所有问题都得到清楚的解答。",
    russianText: "Если у вас останутся вопросы по этому выводу, мы сможем подробно обсудить это на следующем занятии и разобрать дополнительные примеры, чтобы каждый шаг рассуждения стал понятен и ни один вопрос не остался без ответа.",
  },
  {
    id: "mixed",
    label: "中文短句 / 俄文超宽",
    chineseText: "我们明天继续讨论。",
    russianText: "Мы продолжим обсуждать этот вопрос завтра и подробно рассмотрим дополнительные примеры, чтобы каждый участник смог разобраться во всех деталях.",
  },
  {
    id: "chinese-only",
    label: "俄文暂未到达",
    chineseText: "我们明天会继续讨论这个问题。",
    russianText: "",
  },
] as const

export function getSubtitleSample(id: string | null) {
  return subtitleSamples.find((sample) => sample.id === id) ?? subtitleSamples[0]
}
