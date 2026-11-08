export interface SubtitleAppearance {
  chineseFontSize: number
  russianFontSize: number
  showRussian: boolean
  backgroundOpacity: number
  textOpacity: number
  textOutline: boolean
}

export const defaultSubtitleAppearance: SubtitleAppearance = {
  chineseFontSize: 28,
  russianFontSize: 20,
  showRussian: true,
  backgroundOpacity: 45,
  textOpacity: 100,
  textOutline: false,
}
