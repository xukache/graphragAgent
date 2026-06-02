/**
 * Markdown 渲染：react-markdown + remark-gfm（表格/任务列表/删除线/链接）+
 * rehype-highlight（代码高亮）。
 *
 * 安全性：用 AST 渲染，无 dangerouslySetInnerHTML，无 XSS 风险。
 * 性能：流式每 token 触发重渲染——使用 React.memo 包裹外层，
 * 组件内部不缓存 AST，每次重新解析（这是 react-markdown 的标准行为）。
 *
 * 样式：所有 HTML 标签用 token 化的 inline style 注入；代码高亮
 * 通过 `highlight.js/styles/github.css` 提供（main.tsx 已 import）。
 */
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { memo } from 'react';
import { tokens } from '../styles/tokens';

interface MarkdownViewProps {
  content: string;
  /** 当内容正在流式追加时，禁用代码块高亮以减少耗时的 syntax check */
  isStreaming?: boolean;
}

function MarkdownViewImpl({ content, isStreaming }: MarkdownViewProps) {
  return (
    <div className="markdown-body" style={markdownRootStyle}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={isStreaming ? [] : [[rehypeHighlight, { detect: true }]]}
        components={mdComponents}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export const MarkdownView = memo(MarkdownViewImpl);

// --------------------------------------------------------------------- //
// 样式
// --------------------------------------------------------------------- //

const markdownRootStyle: React.CSSProperties = {
  fontSize: 13,
  lineHeight: 1.65,
  color: tokens.text,
  wordBreak: 'break-word',
};

const mdComponents = {
  p: (props: any) => <p style={{ margin: '4px 0' }}>{props.children}</p>,
  h1: (props: any) => (
    <h1 style={{ fontSize: 18, fontWeight: 600, color: tokens.text, margin: '10px 0 4px' }}>
      {props.children}
    </h1>
  ),
  h2: (props: any) => (
    <h2 style={{ fontSize: 15, fontWeight: 600, color: tokens.text, margin: '8px 0 4px' }}>
      {props.children}
    </h2>
  ),
  h3: (props: any) => (
    <h3 style={{ fontSize: 14, fontWeight: 600, color: tokens.text, margin: '6px 0 3px' }}>
      {props.children}
    </h3>
  ),
  h4: (props: any) => (
    <h4 style={{ fontSize: 13, fontWeight: 600, color: tokens.text, margin: '6px 0 3px' }}>
      {props.children}
    </h4>
  ),
  ul: (props: any) => (
    <ul style={{ paddingLeft: 20, margin: '4px 0', listStyleType: 'disc' }}>{props.children}</ul>
  ),
  ol: (props: any) => (
    <ol style={{ paddingLeft: 22, margin: '4px 0', listStyleType: 'decimal' }}>{props.children}</ol>
  ),
  li: (props: any) => <li style={{ margin: '2px 0' }}>{props.children}</li>,
  hr: () => <hr style={{ border: 'none', borderTop: `1px solid ${tokens.border}`, margin: '8px 0' }} />,
  blockquote: (props: any) => (
    <blockquote
      style={{
        margin: '6px 0',
        padding: '4px 10px',
        borderLeft: `3px solid ${tokens.primary}`,
        background: tokens.surface2,
        color: tokens.text2,
        borderRadius: 3,
      }}
    >
      {props.children}
    </blockquote>
  ),
  code: ({ inline, className, children, ...rest }: any) => {
    if (inline) {
      return (
        <code
          style={{
            fontFamily: 'SF Mono, Cascadia Code, monospace',
            fontSize: 12,
            background: tokens.surface2,
            padding: '1px 5px',
            borderRadius: 3,
            color: tokens.primary,
            border: `1px solid ${tokens.border}`,
          }}
          {...rest}
        >
          {children}
        </code>
      );
    }
    return (
      <code className={className} {...rest}>
        {children}
      </code>
    );
  },
  pre: (props: any) => (
    <pre
      style={{
        background: tokens.surface2,
        border: `1px solid ${tokens.border}`,
        borderRadius: 6,
        padding: '10px 12px',
        overflowX: 'auto',
        margin: '6px 0',
        fontSize: 12,
        lineHeight: 1.55,
        fontFamily: 'SF Mono, Cascadia Code, monospace',
      }}
    >
      {props.children}
    </pre>
  ),
  table: (props: any) => (
    <div style={{ overflowX: 'auto', margin: '6px 0' }}>
      <table
        style={{
          width: '100%',
          borderCollapse: 'collapse',
          fontSize: 12,
          background: tokens.surface,
          border: `1px solid ${tokens.border}`,
        }}
      >
        {props.children}
      </table>
    </div>
  ),
  thead: (props: any) => (
    <thead style={{ background: tokens.surface2 }}>{props.children}</thead>
  ),
  th: (props: any) => (
    <th
      style={{
        padding: '6px 10px',
        textAlign: 'left',
        border: `1px solid ${tokens.border}`,
        fontWeight: 600,
        color: tokens.text,
      }}
    >
      {props.children}
    </th>
  ),
  td: (props: any) => (
    <td
      style={{
        padding: '5px 10px',
        border: `1px solid ${tokens.border}`,
        color: tokens.text,
      }}
    >
      {props.children}
    </td>
  ),
  a: (props: any) => (
    <a
      href={props.href}
      target="_blank"
      rel="noreferrer noopener"
      style={{ color: tokens.primary, textDecoration: 'underline' }}
    >
      {props.children}
    </a>
  ),
  img: (props: any) => (
    <img
      src={props.src}
      alt={props.alt || ''}
      style={{ maxWidth: '100%', borderRadius: 4, margin: '4px 0' }}
    />
  ),
  input: (props: any) => {
    if (props.type === 'checkbox') {
      return (
        <input
          type="checkbox"
          checked={!!props.checked}
          readOnly
          style={{ marginRight: 4, accentColor: tokens.primary }}
        />
      );
    }
    return <input {...props} />;
  },
  del: (props: any) => (
    <del style={{ color: tokens.text3 }}>{props.children}</del>
  ),
  strong: (props: any) => <strong style={{ fontWeight: 600, color: tokens.text }}>{props.children}</strong>,
  em: (props: any) => <em style={{ color: tokens.text }}>{props.children}</em>,
} as const;
