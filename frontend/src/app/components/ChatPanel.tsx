import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Plus, X, RotateCcw, Zap, ChevronDown, ChevronRight, Hexagon } from 'lucide-react';
import { Message, Session, Document, Source } from '../types';

interface ChatPanelProps {
  document: Document | null;
  sessions: Session[];
  activeSessionId: string | null;
  messages: Message[];
  isStreaming: boolean;
  onSendMessage: (text: string) => void;
  onNewSession: () => void;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  onRetry: () => void;
  onSourceClick?: (src: Source) => void;
}

function renderMarkdown(text: string): string {
  // 处理代码块（```...```），先提取保护，避免内部内容被其他规则处理
  const codeBlocks: string[] = [];
  let result = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push(
      `<pre style="background:oklch(0.16 0.01 260);border:1px solid oklch(0.26 0.01 260);border-radius:6px;padding:10px 12px;overflow-x:auto;margin:6px 0;font-size:11px;line-height:1.5;"><code style="font-family:SF Mono,Cascadia Code,monospace;color:oklch(0.85 0.005 260);">${escapeHtml(code.trim())}</code></pre>`
    );
    return `\x00CODE${idx}\x00`;
  });

  // 行内代码
  result = result.replace(/`([^`]+)`/g,
    '<code style="font-family:SF Mono,Cascadia Code,monospace;font-size:11px;background:oklch(0.22 0.01 260);padding:1px 5px;border-radius:3px;color:oklch(0.85 0.005 260);">$1</code>'
  );

  // 粗体 / 斜体
  result = result.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  result = result.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  result = result.replace(/\*(.+?)\*/g, '<em>$1</em>');

  // 标题（# ## ###）
  result = result.replace(/^### (.+)$/gm, '<div style="font-size:12px;font-weight:600;color:oklch(0.92 0.005 260);margin:8px 0 3px;">$1</div>');
  result = result.replace(/^## (.+)$/gm, '<div style="font-size:13px;font-weight:600;color:oklch(0.92 0.005 260);margin:10px 0 4px;">$1</div>');
  result = result.replace(/^# (.+)$/gm, '<div style="font-size:14px;font-weight:700;color:oklch(0.92 0.005 260);margin:10px 0 4px;">$1</div>');

  // 无序列表（- 或 *）
  result = result.replace(/^[-*] (.+)$/gm,
    '<div style="display:flex;gap:6px;margin:2px 0;"><span style="color:oklch(0.65 0.18 200);flex-shrink:0;margin-top:1px;">•</span><span>$1</span></div>'
  );

  // 有序列表（1. 2. 等）
  result = result.replace(/^\d+\. (.+)$/gm, (match, content, offset, str) => {
    const num = match.match(/^(\d+)\./)?.[1] ?? '1';
    return `<div style="display:flex;gap:6px;margin:2px 0;"><span style="color:oklch(0.65 0.18 200);flex-shrink:0;min-width:16px;text-align:right;">${num}.</span><span>${content}</span></div>`;
  });

  // 水平线
  result = result.replace(/^---+$/gm, '<hr style="border:none;border-top:1px solid oklch(0.26 0.01 260);margin:8px 0;">');

  // 换行：两个换行变段落间距，单个换行变 <br>
  result = result.replace(/\n\n/g, '<div style="height:6px;"></div>');
  result = result.replace(/\n/g, '<br>');

  // 还原代码块
  result = result.replace(/\x00CODE(\d+)\x00/g, (_, i) => codeBlocks[parseInt(i)]);

  return result;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function TypingDots() {
  return (
    <div style={{ display: 'flex', gap: 4, alignItems: 'center', padding: '4px 0' }}>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          style={{
            width: 5,
            height: 5,
            borderRadius: '50%',
            background: 'oklch(0.65 0.008 260)',
            animation: `bounce 1.2s ease-in-out ${i * 0.2}s infinite`,
          }}
        />
      ))}
      <style>{`
        @keyframes bounce {
          0%, 80%, 100% { transform: translateY(0); opacity: 0.5; }
          40% { transform: translateY(-5px); opacity: 1; }
        }
      `}</style>
    </div>
  );
}

/** 可折叠的工具调用链（竖向列表）。 */
function ToolCallChain({ toolCalls }: { toolCalls: Message['toolCalls'] }) {
  const [expanded, setExpanded] = useState(false);
  if (!toolCalls || toolCalls.length === 0) return null;

  const allDone = toolCalls.every((t) => t.status === 'done');
  const calling = toolCalls.find((t) => t.status === 'calling');

  // 折叠时只显示摘要行
  const summary = allDone
    ? `${toolCalls.length} 次工具调用`
    : calling
    ? `调用 ${calling.name}…`
    : `${toolCalls.length} 次工具调用`;

  return (
    <div
      style={{
        marginBottom: 6,
        background: 'oklch(0.17 0.01 260)',
        border: '1px solid oklch(0.24 0.01 260)',
        borderRadius: 6,
        overflow: 'hidden',
        fontSize: 11,
      }}
    >
      {/* 折叠头 */}
      <button
        onClick={() => setExpanded((v) => !v)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          gap: 5,
          padding: '5px 8px',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          color: allDone ? 'oklch(0.55 0.008 260)' : 'oklch(0.65 0.18 200)',
          textAlign: 'left',
        }}
      >
        {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        <Zap size={10} style={{ flexShrink: 0 }} />
        <span style={{ flex: 1 }}>{summary}</span>
        {!allDone && (
          <span
            style={{
              width: 6, height: 6, borderRadius: '50%',
              background: 'oklch(0.65 0.18 200)',
              animation: 'pulse 1.5s ease-in-out infinite',
              flexShrink: 0,
            }}
          />
        )}
        <style>{`
          @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
        `}</style>
      </button>

      {/* 展开列表 */}
      {expanded && (
        <div
          style={{
            borderTop: '1px solid oklch(0.22 0.01 260)',
            padding: '4px 0',
          }}
        >
          {toolCalls.map((tc, i) => (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '3px 10px',
                color: tc.status === 'done'
                  ? 'oklch(0.65 0.16 155)'
                  : 'oklch(0.65 0.18 200)',
              }}
            >
              {/* 竖线连接符 */}
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 12, flexShrink: 0 }}>
                {i > 0 && (
                  <div style={{ width: 1, height: 6, background: 'oklch(0.28 0.01 260)', marginBottom: 2 }} />
                )}
                <div
                  style={{
                    width: 6, height: 6, borderRadius: '50%',
                    background: tc.status === 'done' ? 'oklch(0.65 0.16 155)' : 'oklch(0.65 0.18 200)',
                    flexShrink: 0,
                    animation: tc.status === 'calling' ? 'pulse 1.5s ease-in-out infinite' : 'none',
                  }}
                />
              </div>
              <span style={{ fontFamily: 'SF Mono, Cascadia Code, monospace', fontSize: 10 }}>
                {tc.name}
              </span>
              {tc.status === 'calling' && (
                <span style={{ color: 'oklch(0.42 0.008 260)', fontSize: 10 }}>调用中…</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ msg, onRetry, onSourceClick }: { msg: Message; onRetry?: () => void; onSourceClick?: (src: Source) => void }) {
  const isUser = msg.role === 'user';
  const isError = msg.isError;

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        padding: '4px 0',
        animation: 'bubbleIn 150ms ease-out',
      }}
    >
      <div style={{ maxWidth: '85%', minWidth: 60 }}>
        {/* Tool calls — 可折叠竖向链 */}
        {msg.toolCalls && msg.toolCalls.length > 0 && (
          <ToolCallChain toolCalls={msg.toolCalls} />
        )}

        {/* Bubble */}
        <div
          style={{
            background: isUser
              ? 'oklch(0.28 0.06 200)'
              : isError
              ? 'oklch(0.22 0.04 25)'
              : 'oklch(0.19 0.01 260)',
            color: isError ? 'oklch(0.75 0.1 25)' : 'oklch(0.92 0.005 260)',
            borderRadius: isUser ? '10px 10px 2px 10px' : '10px 10px 10px 2px',
            padding: '10px 13px',
            fontSize: 13,
            lineHeight: 1.55,
            border: `1px solid ${isUser ? 'oklch(0.65 0.18 200 / 0.3)' : isError ? 'oklch(0.62 0.18 25 / 0.3)' : 'oklch(0.26 0.01 260)'}`,
            wordBreak: 'break-word',
          }}
        >
          {msg.isStreaming && !msg.content ? (
            <TypingDots />
          ) : (
            <>
              <span dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }} />
              {msg.isStreaming && (
                <span
                  style={{
                    display: 'inline-block',
                    width: 2,
                    height: '1em',
                    background: 'oklch(0.65 0.18 200)',
                    marginLeft: 1,
                    verticalAlign: 'text-bottom',
                    animation: 'blink 0.8s step-end infinite',
                  }}
                />
              )}
              <style>{`@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }`}</style>
            </>
          )}
        </div>

        {/* Sources */}
        {msg.sources && msg.sources.length > 0 && !msg.isStreaming && (
          <div
            style={{
              marginTop: 6,
              display: 'flex',
              flexDirection: 'column',
              gap: 3,
            }}
          >
            {msg.sources.map((src, i) => (
              <button
                key={i}
                onClick={() => onSourceClick?.(src)}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'oklch(0.22 0.04 200 / 0.45)';
                  e.currentTarget.style.borderLeftColor = 'oklch(0.65 0.18 200)';
                  e.currentTarget.style.paddingLeft = '10px';
                  const hint = e.currentTarget.querySelector('[data-hint]') as HTMLElement | null;
                  if (hint) hint.style.opacity = '1';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'oklch(0.16 0.01 260)';
                  e.currentTarget.style.borderLeftColor = 'oklch(0.65 0.18 200 / 0.5)';
                  e.currentTarget.style.paddingLeft = '8px';
                  const hint = e.currentTarget.querySelector('[data-hint]') as HTMLElement | null;
                  if (hint) hint.style.opacity = '0';
                }}
                title="点击查看原文片段 + 节点高亮"
                style={{
                  background: 'oklch(0.16 0.01 260)',
                  border: 'none',
                  borderLeft: '2px solid oklch(0.65 0.18 200 / 0.5)',
                  borderRadius: '0 4px 4px 0',
                  padding: '5px 8px',
                  fontSize: 10,
                  color: 'oklch(0.55 0.008 260)',
                  fontFamily: 'SF Mono, Cascadia Code, monospace',
                  cursor: onSourceClick ? 'pointer' : 'default',
                  textAlign: 'left',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 5,
                  transition: 'background 120ms, border-color 120ms, padding 120ms',
                }}
              >
                <Hexagon
                  size={9}
                  color="oklch(0.65 0.18 200 / 0.7)"
                  style={{ flexShrink: 0 }}
                />
                <span style={{ color: 'oklch(0.85 0.005 260)' }}>{src.entityLabel}</span>
                <span style={{ color: 'oklch(0.32 0.008 260)' }}>·</span>
                <span style={{ color: 'oklch(0.42 0.008 260)' }}>{src.entityClass}</span>
                <span style={{ color: 'oklch(0.32 0.008 260)' }}>·</span>
                <span style={{ color: 'oklch(0.42 0.008 260)' }}>{src.location}</span>
                <span
                  data-hint
                  style={{
                    marginLeft: 'auto',
                    color: 'oklch(0.65 0.18 200)',
                    opacity: 0,
                    transition: 'opacity 120ms',
                    fontSize: 9,
                    flexShrink: 0,
                  }}
                >
                  点击查看 →
                </span>
              </button>
            ))}
          </div>
        )}

        {/* Elapsed + retry */}
        {msg.elapsed && !msg.isStreaming && (
          <div style={{ marginTop: 4, color: 'oklch(0.32 0.008 260)', fontSize: 10 }}>
            {msg.elapsed.toFixed(1)}s
          </div>
        )}
        {isError && onRetry && (
          <button
            onClick={onRetry}
            style={{
              marginTop: 6,
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              background: 'none',
              border: '1px solid oklch(0.62 0.18 25 / 0.4)',
              borderRadius: 4,
              color: 'oklch(0.62 0.18 25)',
              fontSize: 11,
              cursor: 'pointer',
              padding: '3px 8px',
            }}
          >
            <RotateCcw size={10} />
            重试
          </button>
        )}
      </div>
      <style>{`
        @keyframes bubbleIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}

function SessionTab({
  session,
  active,
  onSelect,
  onDelete,
}: {
  session: Session;
  active: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onClick={onSelect}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '4px 10px',
        borderRadius: '6px 6px 0 0',
        background: active ? 'oklch(0.12 0.008 260)' : hovered ? 'oklch(0.19 0.01 260)' : 'transparent',
        border: `1px solid ${active ? 'oklch(0.26 0.01 260)' : 'transparent'}`,
        borderBottom: active ? `1px solid oklch(0.12 0.008 260)` : 'none',
        cursor: 'pointer',
        fontSize: 12,
        color: active ? 'oklch(0.92 0.005 260)' : 'oklch(0.55 0.008 260)',
        transition: 'all 150ms',
        whiteSpace: 'nowrap',
        position: 'relative',
        top: 1,
      }}
    >
      {session.name}
      {hovered && (
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            padding: 1,
            color: 'oklch(0.42 0.008 260)',
            display: 'flex',
          }}
        >
          <X size={10} />
        </button>
      )}
    </div>
  );
}

export function ChatPanel({
  document: doc,
  sessions,
  activeSessionId,
  messages,
  isStreaming,
  onSendMessage,
  onNewSession,
  onSelectSession,
  onDeleteSession,
  onRetry,
  onSourceClick,
}: ChatPanelProps) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const docSessions = sessions.filter((s) => s.documentId === doc?.id);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput('');
    onSendMessage(text);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [input, isStreaming, onSendMessage]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const ta = e.target;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
  };

  const isDocReady = doc?.status === 'ready';

  if (!doc) {
    return (
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'oklch(0.42 0.008 260)',
          fontSize: 13,
          gap: 8,
        }}
      >
        <div style={{ fontSize: 32, marginBottom: 8 }}>📄</div>
        <div style={{ color: 'oklch(0.65 0.008 260)', fontWeight: 500 }}>选择一个文档开始问答</div>
        <div style={{ fontSize: 12 }}>或上传新文档以开始使用</div>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0 }}>
      {/* Header */}
      <div
        style={{
          padding: '0 16px',
          borderBottom: '1px solid oklch(0.26 0.01 260)',
          background: 'oklch(0.16 0.01 260)',
          flexShrink: 0,
        }}
      >
        {/* Doc info row */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px 0 6px',
            gap: 8,
          }}
        >
          <div
            style={{
              color: 'oklch(0.75 0.006 260)',
              fontSize: 12,
              fontWeight: 500,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              flex: 1,
            }}
          >
            {doc.name}
          </div>
          {doc.kg && (
            <span style={{ color: 'oklch(0.42 0.008 260)', fontSize: 11, flexShrink: 0 }}>
              {doc.kg.entities} 实体 · {doc.kg.relations} 关系
            </span>
          )}
        </div>

        {/* Session tabs row */}
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3 }}>
          {docSessions.map((sess) => (
            <SessionTab
              key={sess.id}
              session={sess}
              active={sess.id === activeSessionId}
              onSelect={() => onSelectSession(sess.id)}
              onDelete={() => onDeleteSession(sess.id)}
            />
          ))}
          <button
            onClick={onNewSession}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 3,
              padding: '4px 8px',
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'oklch(0.42 0.008 260)',
              fontSize: 11,
              borderRadius: '4px 4px 0 0',
              position: 'relative',
              top: 1,
            }}
          >
            <Plus size={11} />
            新会话
          </button>
        </div>
      </div>

      {/* Messages */}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: 'auto',
          padding: '16px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {messages.length === 0 && isDocReady && (
          <div
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 6,
              color: 'oklch(0.42 0.008 260)',
              fontSize: 13,
            }}
          >
            <div style={{ fontSize: 28 }}>💬</div>
            <div style={{ color: 'oklch(0.65 0.008 260)' }}>开始提问</div>
            <div style={{ fontSize: 12 }}>
              文档已就绪，输入问题即可开始知识图谱问答
            </div>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            msg={msg}
            onRetry={msg.isError ? onRetry : undefined}
            onSourceClick={onSourceClick}
          />
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div
        style={{
          padding: '12px 16px',
          borderTop: '1px solid oklch(0.26 0.01 260)',
          background: 'oklch(0.16 0.01 260)',
          flexShrink: 0,
        }}
      >
        {!isDocReady && (
          <div
            style={{
              marginBottom: 8,
              padding: '6px 10px',
              background: 'oklch(0.22 0.04 80 / 0.3)',
              border: '1px solid oklch(0.72 0.16 80 / 0.3)',
              borderRadius: 6,
              color: 'oklch(0.72 0.16 80)',
              fontSize: 11,
            }}
          >
            文档正在索引中，索引完成后可以开始提问
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            disabled={!isDocReady || isStreaming}
            placeholder={isDocReady ? '输入问题，回车发送，Shift+回车换行…' : '文档索引完成后可提问'}
            rows={1}
            style={{
              flex: 1,
              resize: 'none',
              background: 'oklch(0.19 0.01 260)',
              border: '1px solid oklch(0.26 0.01 260)',
              borderRadius: 8,
              padding: '9px 12px',
              fontSize: 13,
              color: 'oklch(0.92 0.005 260)',
              lineHeight: 1.55,
              minHeight: 38,
              maxHeight: 120,
              outline: 'none',
              fontFamily: 'inherit',
              transition: 'border-color 150ms',
              opacity: !isDocReady || isStreaming ? 0.5 : 1,
            }}
            onFocus={(e) => { e.target.style.borderColor = 'oklch(0.65 0.18 200 / 0.5)'; }}
            onBlur={(e) => { e.target.style.borderColor = 'oklch(0.26 0.01 260)'; }}
          />
          <button
            onClick={handleSend}
            disabled={!isDocReady || isStreaming || !input.trim()}
            style={{
              width: 36,
              height: 36,
              borderRadius: 8,
              background:
                !isDocReady || isStreaming || !input.trim()
                  ? 'oklch(0.22 0.01 260)'
                  : 'oklch(0.65 0.18 200)',
              border: 'none',
              cursor: !isDocReady || isStreaming || !input.trim() ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'oklch(0.92 0.005 260)',
              transition: 'background 150ms',
              flexShrink: 0,
              opacity: !isDocReady || isStreaming || !input.trim() ? 0.4 : 1,
            }}
          >
            <Send size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
