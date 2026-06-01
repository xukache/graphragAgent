import { useEffect, useRef } from 'react';
import { X, FileText } from 'lucide-react';
import type { DrawerSource } from '../types';

interface SourceDrawerProps {
  source: DrawerSource | null;
  pageText: string;
  documentName: string;
  onClose: () => void;
}

const CLASS_COLORS: Record<string, string> = {
  person: 'oklch(0.65 0.18 320)',
  organization: 'oklch(0.65 0.16 30)',
  document: 'oklch(0.65 0.16 155)',
  event: 'oklch(0.72 0.16 80)',
  strategy: 'oklch(0.65 0.18 280)',
  method: 'oklch(0.65 0.15 240)',
  technology: 'oklch(0.65 0.18 160)',
  metric: 'oklch(0.65 0.18 200)',
  default: 'oklch(0.55 0.08 260)',
};

function getClassColor(cls: string): string {
  return CLASS_COLORS[cls.toLowerCase()] ?? CLASS_COLORS.default;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function pageNumberFromId(pageId: string): string {
  const m = pageId.match(/_page_(\d+)$/);
  return m ? `第 ${m[1]} 页` : pageId;
}

export function SourceDrawer({ source, pageText, documentName, onClose }: SourceDrawerProps) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const open = source !== null;

  // Esc 键关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  // 打开时滚动到命中位置
  useEffect(() => {
    if (!open || !source?.charInterval) return;
    const t = setTimeout(() => {
      const mark = bodyRef.current?.querySelector('mark');
      mark?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 60);
    return () => clearTimeout(t);
  }, [open, source?.charInterval?.start_pos, source?.charInterval?.end_pos]);

  if (!source) return null;

  const color = getClassColor(source.entityClass);
  const interval = source.charInterval;
  const hasInterval = interval !== null;

  // 切片
  const safeEnd = Math.min(interval?.end_pos ?? 0, pageText.length);
  const safeStart = Math.max(0, Math.min(interval?.start_pos ?? 0, safeEnd));
  const before = hasInterval ? pageText.slice(0, safeStart) : pageText;
  const middle = hasInterval ? pageText.slice(safeStart, safeEnd) : '';
  const after = hasInterval ? pageText.slice(safeEnd) : '';

  return (
    <>
      {/* 半透明遮罩：覆盖整个父容器，点击关闭 */}
      <div
        onClick={onClose}
        style={{
          position: 'absolute',
          inset: 0,
          background: 'oklch(0 0 0 / 0.35)',
          zIndex: 20,
          animation: 'drawerFadeIn 150ms ease-out',
        }}
      />
      <div
        style={{
          position: 'absolute',
          right: 0,
          top: 0,
          bottom: 0,
          width: '55%',
          minWidth: 360,
          maxWidth: 620,
          background: 'oklch(0.14 0.008 260)',
          borderLeft: '1px solid oklch(0.26 0.01 260)',
          boxShadow: '-4px 0 20px oklch(0 0 0 / 0.5)',
          zIndex: 21,
          display: 'flex',
          flexDirection: 'column',
          animation: 'drawerSlideIn 200ms cubic-bezier(0.25, 1, 0.5, 1)',
        }}
      >
        {/* 头部：文档名 + 页码 + 关闭 */}
        <div
          style={{
            padding: '12px 16px',
            borderBottom: '1px solid oklch(0.26 0.01 260)',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            flexShrink: 0,
          }}
        >
          <FileText size={13} color="oklch(0.55 0.008 260)" />
          <span
            style={{
              color: 'oklch(0.75 0.006 260)',
              fontSize: 12,
              fontWeight: 500,
              flex: 1,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {documentName} · {pageNumberFromId(source.pageId)}
          </span>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: 'oklch(0.55 0.008 260)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 4,
              borderRadius: 4,
            }}
          >
            <X size={14} />
          </button>
        </div>

        {/* 实体行：class 颜色圆点 + label + class badge */}
        <div
          style={{
            padding: '10px 16px',
            borderBottom: '1px solid oklch(0.22 0.01 260)',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            flexShrink: 0,
          }}
        >
          <div
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: color,
              flexShrink: 0,
            }}
          />
          <span style={{ color: color, fontSize: 13, fontWeight: 600 }}>{source.entityLabel}</span>
          <span
            style={{
              background: 'oklch(0.22 0.01 260)',
              padding: '1px 6px',
              borderRadius: 3,
              fontSize: 9,
              color: 'oklch(0.55 0.008 260)',
              textTransform: 'lowercase',
              fontFamily: 'SF Mono, Cascadia Code, monospace',
            }}
          >
            {source.entityClass}
          </span>
        </div>

        {/* 正文：分段 + 命中高亮 */}
        <div
          ref={bodyRef}
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '14px 18px',
            fontSize: 12,
            lineHeight: 1.7,
            color: 'oklch(0.85 0.005 260)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {pageText === '' ? (
            <div
              style={{
                color: 'oklch(0.42 0.008 260)',
                fontSize: 12,
                textAlign: 'center',
                padding: '40px 0',
              }}
            >
              原文暂不可用（文档需重新索引）
            </div>
          ) : (
            <>
              {!hasInterval && (
                <div
                  style={{
                    marginBottom: 12,
                    padding: '6px 10px',
                    background: 'oklch(0.22 0.04 80 / 0.25)',
                    border: '1px solid oklch(0.72 0.16 80 / 0.3)',
                    borderRadius: 4,
                    color: 'oklch(0.72 0.16 80)',
                    fontSize: 11,
                  }}
                >
                  无法定位原文位置（对齐失败），以下为该页全文
                </div>
              )}
              {escapeHtml(before)}
              {hasInterval && (
                <mark
                  style={{
                    background: 'oklch(0.72 0.16 80 / 0.4)',
                    color: 'oklch(0.95 0.005 80)',
                    padding: '1px 2px',
                    borderRadius: 2,
                  }}
                >
                  {escapeHtml(middle)}
                </mark>
              )}
              {escapeHtml(after)}
            </>
          )}
        </div>

        {/* 底部：entity_id */}
        <div
          style={{
            padding: '8px 16px',
            borderTop: '1px solid oklch(0.22 0.01 260)',
            fontSize: 10,
            color: 'oklch(0.32 0.008 260)',
            fontFamily: 'SF Mono, Cascadia Code, monospace',
            flexShrink: 0,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {source.entityId}
        </div>
      </div>
      <style>{`
        @keyframes drawerSlideIn {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
        @keyframes drawerFadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
      `}</style>
    </>
  );
}
