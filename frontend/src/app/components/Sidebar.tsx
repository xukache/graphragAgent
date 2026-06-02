import { useState } from 'react';
import { Upload, ChevronLeft, ChevronRight, FileText, Trash2 } from 'lucide-react';
import { Document } from '../types';
import { tokens } from '../styles/tokens';

interface SidebarProps {
  documents: Document[];
  selectedDocId: string | null;
  collapsed: boolean;
  onSelectDoc: (id: string) => void;
  onDeleteDoc: (id: string) => void;
  onUploadClick: () => void;
  onToggleCollapse: () => void;
}

type PillStyle = { bg: string; color: string; label: string };
const STATUS_PILLS: Record<string, PillStyle> = {
  ready:        { bg: tokens.successSoft, color: tokens.success, label: '就绪' },
  pending:      { bg: tokens.warnSoft,    color: tokens.warn,    label: '等待中' },
  parsing:      { bg: tokens.warnSoft,    color: tokens.warn,    label: '解析' },
  extracting:   { bg: tokens.warnSoft,    color: tokens.warn,    label: '抽取' },
  building_kg:  { bg: tokens.warnSoft,    color: tokens.warn,    label: '建图' },
  failed:       { bg: tokens.errorSoft,   color: tokens.error,   label: '失败' },
};

function StatusPill({ status, progress }: { status: Document['status']; progress?: number }) {
  const base = STATUS_PILLS[status] ?? STATUS_PILLS.pending;
  const label = status === 'parsing' || status === 'extracting' || status === 'building_kg'
    ? `${base.label} ${progress ?? 0}%`
    : base.label;
  return (
    <span
      style={{
        background: base.bg,
        color: base.color,
        borderRadius: 10,
        padding: '1px 7px',
        fontSize: 10,
        fontWeight: 500,
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </span>
  );
}

function DocItem({
  doc,
  selected,
  onSelect,
  onDelete,
}: {
  doc: Document;
  selected: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const [deleteHovered, setDeleteHovered] = useState(false);

  return (
    <div
      onClick={onSelect}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => { setHovered(false); setDeleteHovered(false); }}
      style={{
        padding: '8px 10px',
        borderRadius: 6,
        background: selected
          ? tokens.primarySoft
          : hovered
          ? tokens.surface2
          : 'transparent',
        cursor: 'pointer',
        transition: 'background 120ms',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        position: 'relative',
        borderLeft: selected ? `2px solid ${tokens.primary}` : '2px solid transparent',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6, flex: 1, minWidth: 0 }}>
          <FileText size={13} color={selected ? tokens.primary : tokens.text3} style={{ flexShrink: 0, marginTop: 1 }} />
          <span
            style={{
              color: selected ? tokens.text : tokens.text2,
              fontSize: 12,
              fontWeight: selected ? 500 : 400,
              lineHeight: 1.4,
              wordBreak: 'break-all',
              flex: 1,
            }}
          >
            {doc.name}
          </span>
        </div>
        {hovered && (
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            onMouseEnter={() => setDeleteHovered(true)}
            onMouseLeave={() => setDeleteHovered(false)}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              padding: 2,
              borderRadius: 4,
              color: deleteHovered ? tokens.error : tokens.text3,
              flexShrink: 0,
            }}
            title="删除文档"
          >
            <Trash2 size={11} />
          </button>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingLeft: 19 }}>
        <StatusPill status={doc.status} progress={doc.progress} />
        {doc.kg && (
          <span style={{ color: tokens.text3, fontSize: 10 }}>
            {doc.kg.entities}实 · {doc.kg.relations}边
          </span>
        )}
      </div>
    </div>
  );
}

export function Sidebar({
  documents,
  selectedDocId,
  collapsed,
  onSelectDoc,
  onDeleteDoc,
  onUploadClick,
  onToggleCollapse,
}: SidebarProps) {
  const [uploadHovered, setUploadHovered] = useState(false);

  return (
    <div
      style={{
        width: collapsed ? 0 : 240,
        minWidth: collapsed ? 0 : 240,
        background: tokens.surface,
        borderRight: `1px solid ${tokens.border}`,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        transition: 'width 200ms cubic-bezier(0.25, 1, 0.5, 1), min-width 200ms cubic-bezier(0.25, 1, 0.5, 1)',
        position: 'relative',
        flexShrink: 0,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '12px 12px 8px',
          borderBottom: `1px solid ${tokens.border}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}
      >
        <span style={{
          color: tokens.text2, fontSize: 11, fontWeight: 600,
          letterSpacing: '0.06em', textTransform: 'uppercase',
        }}>
          文档库
        </span>
        <button
          onClick={onUploadClick}
          onMouseEnter={() => setUploadHovered(true)}
          onMouseLeave={() => setUploadHovered(false)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            background: uploadHovered ? tokens.primaryHover : tokens.primary,
            color: tokens.primaryFg,
            border: 'none',
            borderRadius: 5,
            padding: '3px 9px',
            fontSize: 11,
            cursor: 'pointer',
            fontWeight: 500,
            transition: 'background 150ms',
            boxShadow: `0 1px 2px ${tokens.shadow}`,
          }}
        >
          <Upload size={10} />
          上传
        </button>
      </div>

      {/* Document List */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '6px 6px',
          display: 'flex',
          flexDirection: 'column',
          gap: 2,
        }}
      >
        {documents.length === 0 ? (
          <div
            style={{
              padding: '32px 12px',
              textAlign: 'center',
              color: tokens.text3,
              fontSize: 12,
            }}
          >
            <Upload size={20} color={tokens.text3} style={{ margin: '0 auto 8px' }} />
            <p>暂无文档</p>
            <p style={{ fontSize: 11, marginTop: 4 }}>点击上方"上传"添加</p>
          </div>
        ) : (
          documents.map((doc) => (
            <DocItem
              key={doc.id}
              doc={doc}
              selected={doc.id === selectedDocId}
              onSelect={() => onSelectDoc(doc.id)}
              onDelete={() => onDeleteDoc(doc.id)}
            />
          ))
        )}
      </div>

      {/* Footer */}
      <div
        style={{
          padding: '8px 12px',
          borderTop: `1px solid ${tokens.border}`,
          color: tokens.text3,
          fontSize: 11,
          flexShrink: 0,
        }}
      >
        共 {documents.length} 个文档
      </div>

      {/* Collapse toggle */}
      <button
        onClick={onToggleCollapse}
        style={{
          position: 'absolute',
          right: -12,
          top: '50%',
          transform: 'translateY(-50%)',
          width: 22,
          height: 44,
          background: tokens.surface,
          border: `1px solid ${tokens.border}`,
          borderRadius: '0 6px 6px 0',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: tokens.text3,
          zIndex: 10,
          boxShadow: `1px 0 3px ${tokens.shadow}`,
        }}
      >
        {collapsed ? <ChevronRight size={12} /> : <ChevronLeft size={12} />}
      </button>
    </div>
  );
}
