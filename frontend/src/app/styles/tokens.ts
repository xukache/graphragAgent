/**
 * 语义颜色 + 排版 token（清新主题，浅色为主，OKLCH 表达）。
 *
 * 单一来源：theme.css 的 CSS 变量 → 此处的 TS 常量（与 CSS 变量名一一对应）。
 * 业务组件用 var(--xxx) 或 import 此处的常量都可，二者切换 0 成本。
 *
 * 色彩规范（OKLCH 表达）：
 * - 浅色为默认；深色仅在 prefers-color-scheme / 显式 .dark 时启用
 * - 关键前景/背景对比度满足 WCAG AA
 * - KG 节点类色 hue 间隔 ≥30°，避开红绿混淆
 */
export const tokens = {
  // ---- 中性层 ----
  bg:           'var(--bg)',
  surface:      'var(--surface)',
  surface2:     'var(--surface-2)',
  border:       'var(--border)',
  borderStrong: 'var(--border-strong)',

  // ---- 文字 ----
  text:         'var(--text)',
  text2:        'var(--text-2)',
  text3:        'var(--text-3)',
  textInverse:  'var(--text-inverse)',

  // ---- 语义色 ----
  primary:        'var(--primary)',
  primaryHover:   'var(--primary-hover)',
  primarySoft:    'var(--primary-soft)',
  primaryFg:      'var(--primary-fg)',
  success:        'var(--success)',
  successSoft:    'var(--success-soft)',
  warn:           'var(--warn)',
  warnSoft:       'var(--warn-soft)',
  error:          'var(--error)',
  errorSoft:      'var(--error-soft)',

  // ---- 阴影 / 遮罩 ----
  shadow:       'var(--shadow)',
  overlay:      'var(--overlay)',

  // ---- 排版 ----
  radius:       'var(--radius)',
  radiusSm:     'var(--radius-sm)',
  radiusMd:     'var(--radius-md)',
  radiusLg:     'var(--radius-lg)',

  // ---- KG 节点类色（与新 KG 小写 entity_class 对齐） ----
  kgClass: {
    author:              'oklch(0.60 0.14 320)',
    institution:         'oklch(0.60 0.13 30)',
    method:              'oklch(0.55 0.14 240)',
    technique:           'oklch(0.58 0.13 200)',
    concept:             'oklch(0.55 0.13 280)',
    task:                'oklch(0.55 0.12 100)',
    component:           'oklch(0.60 0.13 50)',
    challenge:           'oklch(0.55 0.14 0)',
    domain:              'oklch(0.55 0.10 180)',
    reference:           'oklch(0.55 0.10 90)',
    application_domain:  'oklch(0.55 0.11 160)',
    data_structure:      'oklch(0.55 0.12 220)',
    community:           'oklch(0.55 0.10 260)',
    section:             'oklch(0.55 0.10 110)',
    default:             'oklch(0.55 0.05 250)',
  } as const,
} as const;

export type TokenKey = keyof typeof tokens;
export type KgClassKey = keyof typeof tokens.kgClass;

/**
 * 根据 KG 实体类名查色：精确匹配（不区分大小写），未命中返回 default。
 * 设计原则：hue 间隔 ≥30° 避免混淆；与新 KG 的小写 entity_class 字段对齐。
 */
export function kgClassColor(cls: string): string {
  const k = cls.toLowerCase() as KgClassKey;
  return (tokens.kgClass as Record<string, string>)[k] ?? tokens.kgClass.default;
}
