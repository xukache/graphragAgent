import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Plus, X, RotateCcw, Zap, ChevronDown, ChevronRight, Hexagon, Copy, Check, MoreHorizontal, Pencil, Eraser, Trash2 } from 'lucide-react';
import { Message, Session, Document, Source } from '../types';
import { tokens } from '../styles/tokens';
import { MarkdownView } from './MarkdownView';
import { toast } from 'sonner';

interface ChatPanelProps {
  document: Document | null;
  sessions: Session[];
  activeSessionId: string | null;
  messages: Message[];
  isStreaming: boolean;
  /** 当前会话消息是否仍在加载（用于切换时显示骨架） */
  sessionLoading?: boolean;
  onSendMessage: (text: string) => void;
  onNewSession: () => void;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  /** 重命名会话（id, newTitle） */
  onRenameSession?: (id: string, title: string) => void | Promise<void>;
  /** 清空会话内的所有消息（保留会话） */
  onClearMessages?: (id: string) => void | Promise<void>;
  onRetry: () => void;
  onSourceClick?: (src: Source) => void;
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
            background: tokens.text3,
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

/** 可折叠的工具调用链 */
function ToolCallChain({ toolCalls }: { toolCalls: Message['toolCalls'] }) {
  const [expanded, setExpanded] = useState(false);
  if (!toolCalls || toolCalls.length === 0) return null;

  const allDone = toolCalls.every((t) => t.status === 'done');
  const calling = toolCalls.find((t) => t.status === 'calling');

  const summary = allDone
    ? `${toolCalls.length} 次工具调用`
    : calling
    ? `调用 ${calling.name}…`
    : `${toolCalls.length} 次工具调用`;

  return (
    <div
      style={{
        marginBottom: 6,
        background: tokens.surface2,
        border: `1px solid ${tokens.border}`,
        borderRadius: 6,
        overflow: 'hidden',
        fontSize: 11,
      }}
    >
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
          color: allDone ? tokens.text2 : tokens.primary,
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
              background: tokens.primary,
              animation: 'pulse 1.5s ease-in-out infinite',
              flexShrink: 0,
            }}
          />
        )}
        <style>{`
          @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
        `}</style>
      </button>

      {expanded && (
        <div
          style={{
            borderTop: `1px solid ${tokens.border}`,
            padding: '4px 0',
            background: tokens.surface,
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
                color: tc.status === 'done' ? tokens.success : tokens.primary,
              }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 12, flexShrink: 0 }}>
                {i > 0 && (
                  <div style={{ width: 1, height: 6, background: tokens.borderStrong, marginBottom: 2 }} />
                )}
                <div
                  style={{
                    width: 6, height: 6, borderRadius: '50%',
                    background: tc.status === 'done' ? tokens.success : tokens.primary,
                    flexShrink: 0,
                    animation: tc.status === 'calling' ? 'pulse 1.5s ease-in-out infinite' : 'none',
                  }}
                />
              </div>
              <span style={{ fontFamily: 'SF Mono, Cascadia Code, monospace', fontSize: 10 }}>
                {tc.name}
              </span>
              {tc.status === 'calling' && (
                <span style={{ color: tokens.text3, fontSize: 10 }}>调用中…</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** 单条消息气泡：包含复制按钮、retry 等。 */
function MessageBubble({
  msg,
  onRetry,
  onCopy,
  onSourceClick,
}: {
  msg: Message;
  onRetry?: () => void;
  onCopy?: (text: string) => void;
  onSourceClick?: (src: Source) => void;
}) {
  const isUser = msg.role === 'user';
  const isError = msg.isError;
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    if (!onCopy) return;
    onCopy(msg.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [msg.content, onCopy]);

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        padding: '4px 0',
        animation: 'bubbleIn 150ms ease-out',
      }}
    >
      <div style={{ maxWidth: '85%', minWidth: 60, position: 'relative' }}>
        {msg.toolCalls && msg.toolCalls.length > 0 && (
          <ToolCallChain toolCalls={msg.toolCalls} />
        )}

        <div
          style={{
            background: isUser
              ? tokens.primary
              : isError
              ? tokens.errorSoft
              : tokens.surface,
            color: isUser ? tokens.primaryFg : isError ? tokens.error : tokens.text,
            borderRadius: isUser ? '10px 10px 2px 10px' : '10px 10px 10px 2px',
            padding: '10px 13px',
            fontSize: 13,
            lineHeight: 1.55,
            border: `1px solid ${
              isUser ? tokens.primary
              : isError ? tokens.error
              : tokens.border
            }`,
            wordBreak: 'break-word',
            boxShadow: `0 1px 2px ${tokens.shadow}`,
          }}
        >
          {msg.isStreaming && !msg.content ? (
            <TypingDots />
          ) : (
            <>
              {isUser ? (
                <span style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</span>
              ) : (
                <MarkdownView content={msg.content} isStreaming={msg.isStreaming} />
              )}
              {msg.isStreaming && (
                <span
                  style={{
                    display: 'inline-block',
                    width: 2,
                    height: '1em',
                    background: tokens.primary,
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

        {/* Hover 工具栏：复制 + retry */}
        {!msg.isStreaming && !isError && msg.content && (
          <div
            className="msg-toolbar"
            style={{
              position: 'absolute',
              top: -8,
              right: isUser ? 0 : 'auto',
              left: isUser ? 'auto' : 0,
              display: 'flex',
              gap: 2,
              opacity: 0,
              background: tokens.surface,
              border: `1px solid ${tokens.border}`,
              borderRadius: 4,
              padding: 1,
              boxShadow: `0 2px 6px ${tokens.shadow}`,
              transition: 'opacity 120ms',
              pointerEvents: 'none',
            }}
          >
            <button
              onClick={handleCopy}
              title={copied ? '已复制' : '复制消息'}
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                padding: 3,
                borderRadius: 3,
                color: copied ? tokens.success : tokens.text2,
                display: 'flex',
                alignItems: 'center',
                pointerEvents: 'auto',
              }}
            >
              {copied ? <Check size={11} /> : <Copy size={11} />}
            </button>
          </div>
        )}

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
                  e.currentTarget.style.background = tokens.primarySoft;
                  e.currentTarget.style.borderLeftColor = tokens.primary;
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = tokens.surface2;
                  e.currentTarget.style.borderLeftColor = tokens.primary;
                }}
                title="点击查看原文片段 + 节点高亮"
                style={{
                  background: tokens.surface2,
                  border: 'none',
                  borderLeft: `2px solid ${tokens.primary}`,
                  borderRadius: '0 4px 4px 0',
                  padding: '5px 8px',
                  fontSize: 10,
                  color: tokens.text2,
                  fontFamily: 'SF Mono, Cascadia Code, monospace',
                  textAlign: 'left',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 5,
                  transition: 'background 120ms',
                }}
              >
                <Hexagon size={9} color={tokens.primary} style={{ flexShrink: 0 }} />
                <span style={{ color: tokens.text }}>{src.entityLabel}</span>
                <span style={{ color: tokens.text3 }}>·</span>
                <span style={{ color: tokens.text2 }}>{src.entityClass}</span>
                <span style={{ color: tokens.text3 }}>·</span>
                <span style={{ color: tokens.text2 }}>{src.location}</span>
              </button>
            ))}
          </div>
        )}

        {/* Elapsed + retry */}
        {msg.elapsed && !msg.isStreaming && (
          <div style={{ marginTop: 4, color: tokens.text3, fontSize: 10 }}>
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
              border: `1px solid ${tokens.error}`,
              borderRadius: 4,
              color: tokens.error,
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
        /* Hover 工具栏显示 */
        [style*="position: absolute"]:hover > .msg-toolbar,
        .msg-toolbar:hover {
          opacity: 1 !important;
          pointer-events: auto !important;
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
  onRename,
  onClearMessages,
}: {
  session: Session;
  active: boolean;
  onSelect: () => void;
  onDelete: () => void;
  onRename?: (newTitle: string) => void | Promise<void>;
  onClearMessages?: () => void | Promise<void>;
}) {
  const [hovered, setHovered] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState(session.name);

  const startEdit = () => {
    setDraftTitle(session.name);
    setEditing(true);
    setMenuOpen(false);
  };

  const commitEdit = async () => {
    const trimmed = draftTitle.trim();
    setEditing(false);
    if (trimmed && trimmed !== session.name && onRename) {
      await onRename(trimmed);
    }
  };

  return (
    <div
      onClick={editing ? undefined : onSelect}
      onDoubleClick={startEdit}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => { setHovered(false); setMenuOpen(false); }}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '4px 4px 4px 10px',
        borderRadius: '6px 6px 0 0',
        background: active ? tokens.bg : hovered ? tokens.surface2 : 'transparent',
        border: `1px solid ${active ? tokens.border : 'transparent'}`,
        borderBottom: active ? `1px solid ${tokens.bg}` : 'none',
        cursor: 'pointer',
        fontSize: 12,
        color: active ? tokens.text : tokens.text2,
        transition: 'all 150ms',
        whiteSpace: 'nowrap',
        position: 'relative',
        top: 1,
        fontWeight: active ? 500 : 400,
      }}
    >
      {editing ? (
        <input
          autoFocus
          value={draftTitle}
          onChange={(e) => setDraftTitle(e.target.value)}
          onBlur={commitEdit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commitEdit();
            if (e.key === 'Escape') setEditing(false);
          }}
          onClick={(e) => e.stopPropagation()}
          style={{
            background: 'transparent',
            border: 'none',
            outline: 'none',
            fontSize: 12,
            color: tokens.text,
            minWidth: 60,
            maxWidth: 160,
          }}
        />
      ) : (
        <span style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis' }}>{session.name}</span>
      )}

      {hovered && !editing && (
        <>
          <button
            onClick={(e) => { e.stopPropagation(); setMenuOpen((v) => !v); }}
            title="更多"
            style={{
              background: menuOpen ? tokens.surface2 : 'transparent',
              border: 'none',
              cursor: 'pointer',
              padding: 1,
              color: tokens.text2,
              display: 'flex',
              borderRadius: 3,
            }}
          >
            <MoreHorizontal size={11} />
          </button>
          {menuOpen && (
            <div
              onClick={(e) => e.stopPropagation()}
              style={{
                position: 'absolute',
                top: '100%',
                left: 0,
                marginTop: 4,
                background: tokens.surface,
                border: `1px solid ${tokens.border}`,
                borderRadius: 6,
                boxShadow: `0 4px 12px ${tokens.shadow}`,
                zIndex: 50,
                minWidth: 140,
                padding: 4,
                display: 'flex',
                flexDirection: 'column',
                gap: 1,
              }}
            >
              <MenuItem icon={Pencil} label="重命名" onClick={startEdit} />
              <MenuItem
                icon={Eraser}
                label="清空消息"
                danger
                onClick={async () => {
                  if (!onClearMessages) return;
                  if (window.confirm('确认清空该会话内的所有消息？此操作不可撤销。')) {
                    await onClearMessages();
                    toast.success('已清空会话消息');
                  }
                  setMenuOpen(false);
                }}
              />
              <MenuItem
                icon={Trash2}
                label="删除会话"
                danger
                onClick={() => {
                  if (window.confirm(`确认删除会话"${session.name}"？`)) {
                    onDelete();
                    toast.success('会话已删除');
                  }
                  setMenuOpen(false);
                }}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function MenuItem({
  icon: Icon,
  label,
  onClick,
  danger,
}: {
  icon: any;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        background: hovered ? (danger ? tokens.errorSoft : tokens.surface2) : 'transparent',
        color: danger ? tokens.error : tokens.text,
        border: 'none',
        padding: '5px 8px',
        borderRadius: 4,
        fontSize: 12,
        cursor: 'pointer',
        textAlign: 'left',
        width: '100%',
      }}
    >
      <Icon size={11} />
      {label}
    </button>
  );
}

export function ChatPanel({
  document: doc,
  sessions,
  activeSessionId,
  messages,
  isStreaming,
  sessionLoading,
  onSendMessage,
  onNewSession,
  onSelectSession,
  onDeleteSession,
  onRenameSession,
  onClearMessages,
  onRetry,
  onSourceClick,
}: ChatPanelProps) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  /** 智能滚动：用户是否在底部；离开底部后停止自动跟随 */
  const [autoFollow, setAutoFollow] = useState(true);
  const prevMsgCountRef = useRef(0);

  const docSessions = sessions.filter((s) => s.documentId === doc?.id);

  // 智能滚动：消息数变化时，如果用户处于底部，自动滚到底
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const newCount = messages.length;
    const isInitial = prevMsgCountRef.current === 0 && newCount > 0;
    prevMsgCountRef.current = newCount;

    if (autoFollow || isInitial) {
      requestAnimationFrame(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: isInitial ? 'auto' : 'smooth' });
      });
    }
  }, [messages, autoFollow]);

  // 监听容器滚动，判断用户是否在底部（距底 32px 内视为在底部）
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const onScroll = () => {
      const distFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
      setAutoFollow(distFromBottom < 32);
    };
    container.addEventListener('scroll', onScroll, { passive: true });
    return () => container.removeEventListener('scroll', onScroll);
  }, []);

  // 用户滚到底部后，重新开启 auto-follow
  useEffect(() => {
    if (autoFollow) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [autoFollow]);

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

  const handleCopy = useCallback((text: string) => {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(
        () => toast.success('已复制到剪贴板'),
        () => fallbackCopy(text)
      );
    } else {
      fallbackCopy(text);
    }
  }, []);

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
          background: tokens.bg,
          color: tokens.text3,
          fontSize: 13,
          gap: 8,
        }}
      >
        <div style={{ fontSize: 32, marginBottom: 8 }}>📄</div>
        <div style={{ color: tokens.text, fontWeight: 500 }}>选择一个文档开始问答</div>
        <div style={{ fontSize: 12 }}>或上传新文档以开始使用</div>
      </div>
    );
  }

  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      minWidth: 0, minHeight: 0, background: tokens.bg,
    }}>
      {/* Header */}
      <div
        style={{
          padding: '0 16px',
          borderBottom: `1px solid ${tokens.border}`,
          background: tokens.surface,
          flexShrink: 0,
        }}
      >
        {/* Doc info row */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 0 6px',
            gap: 8,
          }}
        >
          <div
            style={{
              color: tokens.text,
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
            <span style={{ color: tokens.text3, fontSize: 11, flexShrink: 0 }}>
              {doc.kg.entities} 实体 · {doc.kg.relations} 关系
            </span>
          )}
        </div>

        {/* Session tabs row */}
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, flexWrap: 'wrap' }}>
          {docSessions.map((sess) => (
            <SessionTab
              key={sess.id}
              session={sess}
              active={sess.id === activeSessionId}
              onSelect={() => onSelectSession(sess.id)}
              onDelete={() => onDeleteSession(sess.id)}
              onRename={onRenameSession ? (t) => onRenameSession(sess.id, t) : undefined}
              onClearMessages={onClearMessages ? () => onClearMessages(sess.id) : undefined}
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
              color: tokens.text3,
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
        ref={scrollContainerRef}
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: 'auto',
          padding: '16px',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {sessionLoading ? (
          <div
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: tokens.text3,
              fontSize: 12,
              gap: 8,
            }}
          >
            <span
              style={{
                width: 14, height: 14,
                border: `2px solid ${tokens.border}`,
                borderTopColor: tokens.primary,
                borderRadius: '50%',
                animation: 'spin 0.8s linear infinite',
              }}
            />
            加载消息…
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
          </div>
        ) : messages.length === 0 && isDocReady ? (
          <div
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
              color: tokens.text3,
              fontSize: 13,
            }}
          >
            <div style={{ fontSize: 28 }}>💬</div>
            <div style={{ color: tokens.text, fontWeight: 500 }}>开始提问</div>
            <div style={{ fontSize: 12, textAlign: 'center', maxWidth: 320 }}>
              文档已就绪，输入问题即可开始知识图谱问答<br />
              <span style={{ color: tokens.text3, fontSize: 11 }}>例如：「这篇论文用了哪些方法？」「Q1 营收多少？」</span>
            </div>
          </div>
        ) : !isDocReady ? (
          <div
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: tokens.text3,
              fontSize: 12,
            }}
          >
            文档尚未就绪，请等待索引完成
          </div>
        ) : null}

        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            msg={msg}
            onRetry={msg.isError ? onRetry : undefined}
            onCopy={handleCopy}
            onSourceClick={onSourceClick}
          />
        ))}

        {!autoFollow && messages.length > 0 && (
          <button
            onClick={() => {
              setAutoFollow(true);
              messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
            }}
            style={{
              position: 'sticky',
              bottom: 8,
              alignSelf: 'center',
              background: tokens.surface,
              border: `1px solid ${tokens.border}`,
              borderRadius: 14,
              padding: '4px 12px',
              fontSize: 11,
              color: tokens.text2,
              cursor: 'pointer',
              boxShadow: `0 2px 6px ${tokens.shadow}`,
              display: 'flex',
              alignItems: 'center',
              gap: 4,
            }}
          >
            <ChevronDown size={11} />
            回到最新
          </button>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div
        style={{
          padding: '12px 16px',
          borderTop: `1px solid ${tokens.border}`,
          background: tokens.surface,
          flexShrink: 0,
        }}
      >
        {!isDocReady && (
          <div
            style={{
              marginBottom: 8,
              padding: '6px 10px',
              background: tokens.warnSoft,
              border: `1px solid ${tokens.warn}`,
              borderRadius: 6,
              color: tokens.warn,
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
              background: tokens.bg,
              border: `1px solid ${tokens.border}`,
              borderRadius: 8,
              padding: '9px 12px',
              fontSize: 13,
              color: tokens.text,
              lineHeight: 1.55,
              minHeight: 38,
              maxHeight: 120,
              outline: 'none',
              fontFamily: 'inherit',
              transition: 'border-color 150ms',
              opacity: !isDocReady || isStreaming ? 0.5 : 1,
            }}
            onFocus={(e) => { e.target.style.borderColor = tokens.primary; }}
            onBlur={(e) => { e.target.style.borderColor = tokens.border; }}
          />
          <button
            onClick={handleSend}
            disabled={!isDocReady || isStreaming || !input.trim()}
            style={{
              width: 36,
              height: 36,
              borderRadius: 8,
              background: !isDocReady || isStreaming || !input.trim()
                ? tokens.surface2
                : tokens.primary,
              border: 'none',
              cursor: !isDocReady || isStreaming || !input.trim() ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: !isDocReady || isStreaming || !input.trim() ? tokens.text3 : tokens.primaryFg,
              transition: 'background 150ms',
              flexShrink: 0,
            }}
          >
            <Send size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}

function fallbackCopy(text: string) {
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    toast.success('已复制到剪贴板');
  } catch {
    toast.error('复制失败，请手动选择');
  }
}
