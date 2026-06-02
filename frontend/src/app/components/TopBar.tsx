import { Network } from 'lucide-react';
import { tokens } from '../styles/tokens';

interface TopBarProps {
  healthy: boolean;
}

export function TopBar({ healthy }: TopBarProps) {
  return (
    <header
      style={{
        height: 44,
        background: tokens.surface,
        borderBottom: `1px solid ${tokens.border}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 16px',
        flexShrink: 0,
        zIndex: 100,
        boxShadow: `0 1px 2px ${tokens.shadow}`,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div
          style={{
            width: 26,
            height: 26,
            background: tokens.primary,
            borderRadius: 7,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: `0 1px 3px ${tokens.shadow}`,
          }}
        >
          <Network size={14} color={tokens.primaryFg} />
        </div>
        <span
          style={{
            color: tokens.text,
            fontWeight: 600,
            fontSize: 14,
            letterSpacing: '0.01em',
          }}
        >
          GraphRAG
        </span>
        <span
          style={{
            color: tokens.text3,
            fontSize: 11,
            marginLeft: 4,
            paddingLeft: 8,
            borderLeft: `1px solid ${tokens.border}`,
          }}
        >
          多模态知识问答
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <div
          style={{
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: healthy ? tokens.success : tokens.error,
            boxShadow: healthy
              ? `0 0 6px ${tokens.success}`
              : `0 0 6px ${tokens.error}`,
          }}
        />
        <span style={{ color: tokens.text2, fontSize: 11 }}>
          {healthy ? '系统正常' : '服务异常'}
        </span>
      </div>
    </header>
  );
}
