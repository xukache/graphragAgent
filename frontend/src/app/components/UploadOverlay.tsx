import { useState, useRef, useCallback } from 'react';
import { Upload, X, FileText, AlertCircle, Loader } from 'lucide-react';
import { tokens } from '../styles/tokens';

interface UploadOverlayProps {
  onClose: () => void;
  onUpload: (file: File) => void;
}

const ACCEPTED_TYPES = [
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.ms-powerpoint',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'image/jpeg',
  'image/png',
  'image/gif',
  'image/webp',
  'text/html',
];

const FORMAT_LABELS = 'PDF / Word / PPT / Excel / 图片 / HTML';
const MAX_SIZE_MB = 200;

export function UploadOverlay({ onClose, onUpload }: UploadOverlayProps) {
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const validateFile = (file: File): string | null => {
    if (!ACCEPTED_TYPES.includes(file.type) && !file.name.match(/\.(pdf|doc|docx|ppt|pptx|xls|xlsx|jpg|jpeg|png|gif|webp|html|htm)$/i)) {
      return '不支持该文件格式，请上传 PDF / Word / PPT / Excel / 图片 / HTML';
    }
    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      return `文件大小超过限制（最大 ${MAX_SIZE_MB}MB）`;
    }
    return null;
  };

  const handleFile = useCallback(
    (file: File) => {
      const err = validateFile(file);
      if (err) {
        setError(err);
        return;
      }
      setError(null);
      setUploading(true);
      setTimeout(() => {
        onUpload(file);
      }, 600);
    },
    [onUpload]
  );

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(true);
  };

  const handleDragLeave = () => setDragging(false);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: tokens.overlay,
        backdropFilter: 'blur(6px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 200,
        animation: 'overlayIn 200ms ease-out',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: tokens.surface,
          border: `1px solid ${tokens.border}`,
          borderRadius: 12,
          padding: 28,
          width: 420,
          maxWidth: '90vw',
          boxShadow: `0 8px 32px ${tokens.shadow}`,
          animation: 'cardIn 200ms ease-out',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div>
            <div style={{ color: tokens.text, fontSize: 15, fontWeight: 600 }}>
              上传文档
            </div>
            <div style={{ color: tokens.text3, fontSize: 11, marginTop: 2 }}>
              支持 {FORMAT_LABELS}，最大 {MAX_SIZE_MB}MB
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: tokens.text3,
              padding: 4,
              borderRadius: 4,
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Drop zone */}
        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onClick={() => !uploading && fileInputRef.current?.click()}
          style={{
            border: `2px dashed ${dragging ? tokens.primary : error ? tokens.error : tokens.border}`,
            borderRadius: 10,
            padding: '36px 24px',
            textAlign: 'center',
            cursor: uploading ? 'not-allowed' : 'pointer',
            transition: 'border-color 200ms, background 200ms',
            background: dragging
              ? tokens.primarySoft
              : tokens.bg,
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.jpg,jpeg,png,gif,webp,html,htm"
            onChange={handleFileSelect}
            style={{ display: 'none' }}
          />

          {uploading ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
              <Loader
                size={28}
                color={tokens.primary}
                style={{ animation: 'spin 1s linear infinite' }}
              />
              <div style={{ color: tokens.text2, fontSize: 13 }}>正在上传…</div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
              {dragging ? (
                <FileText size={32} color={tokens.primary} />
              ) : (
                <Upload size={28} color={tokens.text3} />
              )}
              <div>
                <div style={{
                  color: dragging ? tokens.primary : tokens.text,
                  fontSize: 13, fontWeight: 500,
                }}>
                  {dragging ? '松开鼠标上传' : '拖拽文件到此处'}
                </div>
                <div style={{ color: tokens.text3, fontSize: 11, marginTop: 4 }}>
                  或<span style={{ color: tokens.primary, marginLeft: 4, fontWeight: 500 }}>点击选择文件</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Error */}
        {error && (
          <div
            style={{
              marginTop: 10,
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              color: tokens.error,
              fontSize: 12,
            }}
          >
            <AlertCircle size={13} />
            {error}
          </div>
        )}

        {/* Format tags */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 16 }}>
          {['PDF', 'Word', 'PPT', 'Excel', 'PNG/JPG', 'HTML'].map((fmt) => (
            <span
              key={fmt}
              style={{
                background: tokens.surface2,
                border: `1px solid ${tokens.border}`,
                borderRadius: 4,
                padding: '2px 8px',
                fontSize: 11,
                color: tokens.text2,
              }}
            >
              {fmt}
            </span>
          ))}
        </div>
      </div>

      <style>{`
        @keyframes overlayIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes cardIn {
          from { opacity: 0; transform: scale(0.96) translateY(8px); }
          to { opacity: 1; transform: scale(1) translateY(0); }
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
