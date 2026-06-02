import { CheckCircle, Circle, AlertCircle, Loader } from 'lucide-react';
import { tokens } from '../styles/tokens';

export type StageStatus = 'waiting' | 'active' | 'done' | 'error';

export interface StageState {
  status: StageStatus;
  progress: number;
  elapsed?: number;
  detail?: string;
  error?: string;
}

export interface IndexProgressProps {
  docName: string;
  stages: {
    parsing: StageState;
    extracting: StageState;
    building_kg: StageState;
  };
}

const STAGE_LABELS = {
  parsing: { label: '文档解析', desc: 'MinerU 提取文本、表格、图片' },
  extracting: { label: '信息抽取', desc: 'LangExtract 识别实体和关系' },
  building_kg: { label: '知识图谱构建', desc: '构建图谱节点和边' },
};

function StageRow({ id, state }: { id: keyof typeof STAGE_LABELS; state: StageState }) {
  const meta = STAGE_LABELS[id];
  const isActive = state.status === 'active';
  const isDone = state.status === 'done';
  const isError = state.status === 'error';

  const iconColor = isDone ? tokens.success
    : isActive ? tokens.warn
    : isError ? tokens.error
    : tokens.text3;

  const labelColor = isDone || isActive ? tokens.text
    : isError ? tokens.error
    : tokens.text2;

  return (
    <div
      style={{
        padding: '12px 16px',
        borderRadius: 8,
        background: isActive
          ? tokens.primarySoft
          : isDone
          ? tokens.successSoft
          : tokens.surface,
        border: `1px solid ${
          isActive ? tokens.primary
          : isDone ? tokens.success
          : isError ? tokens.error
          : tokens.border
        }`,
        transition: 'all 300ms cubic-bezier(0.25, 1, 0.5, 1)',
        boxShadow: `0 1px 2px ${tokens.shadow}`,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: isActive ? 10 : 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ flexShrink: 0 }}>
            {isDone && <CheckCircle size={16} color={iconColor} />}
            {isActive && (
              <Loader
                size={16}
                color={iconColor}
                style={{ animation: 'spin 1s linear infinite' }}
              />
            )}
            {isError && <AlertCircle size={16} color={iconColor} />}
            {(!isDone && !isActive && !isError) && <Circle size={16} color={iconColor} />}
          </div>
          <div>
            <div style={{ color: labelColor, fontSize: 13, fontWeight: 500 }}>{meta.label}</div>
            <div style={{ color: tokens.text3, fontSize: 11, marginTop: 1 }}>{meta.desc}</div>
          </div>
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0 }}>
          {isActive && (
            <span style={{ color: tokens.warn, fontSize: 12, fontWeight: 600 }}>
              {state.progress}%
            </span>
          )}
          {isDone && state.elapsed && (
            <span style={{ color: tokens.text3, fontSize: 11 }}>
              {state.elapsed.toFixed(1)}s
            </span>
          )}
          {isError && (
            <span style={{ color: tokens.error, fontSize: 11, fontWeight: 500 }}>
              失败
            </span>
          )}
        </div>
      </div>

      {isActive && (
        <div style={{ marginTop: 4 }}>
          <div
            style={{
              height: 3,
              background: tokens.border,
              borderRadius: 2,
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                height: '100%',
                width: `${state.progress}%`,
                background: tokens.primary,
                borderRadius: 2,
                transition: 'width 400ms ease-out',
              }}
            />
          </div>
          {state.detail && (
            <div style={{ color: tokens.text3, fontSize: 10, marginTop: 4 }}>
              {state.detail}
            </div>
          )}
        </div>
      )}

      {isError && state.error && (
        <div
          style={{
            marginTop: 8,
            padding: '6px 8px',
            background: tokens.errorSoft,
            borderRadius: 4,
            color: tokens.error,
            fontSize: 11,
            border: `1px solid ${tokens.error}`,
          }}
        >
          {state.error}
        </div>
      )}
    </div>
  );
}

export function IndexProgress({ docName, stages }: IndexProgressProps) {
  const allDone = Object.values(stages).every((s) => s.status === 'done');
  const hasError = Object.values(stages).some((s) => s.status === 'error');

  const totalProgress =
    (stages.parsing.progress + stages.extracting.progress + stages.building_kg.progress) / 3;

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '40px 32px',
        background: tokens.bg,
      }}
    >
      <div style={{ width: '100%', maxWidth: 520 }}>
        {/* Header */}
        <div style={{ marginBottom: 24, textAlign: 'center' }}>
          <div style={{ color: tokens.text, fontSize: 16, fontWeight: 600, marginBottom: 4 }}>
            正在索引文档
          </div>
          <div
            style={{
              color: tokens.text2,
              fontSize: 12,
              maxWidth: 320,
              margin: '0 auto',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {docName}
          </div>
        </div>

        {/* Overall progress */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <span style={{ color: tokens.text2, fontSize: 11 }}>总进度</span>
            <span style={{ color: tokens.text2, fontSize: 11 }}>
              {hasError ? '索引失败' : allDone ? '索引完成' : `${Math.round(totalProgress)}%`}
            </span>
          </div>
          <div
            style={{
              height: 4,
              background: tokens.border,
              borderRadius: 2,
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                height: '100%',
                width: hasError ? '100%' : `${totalProgress}%`,
                background: hasError
                  ? tokens.error
                  : allDone
                  ? tokens.success
                  : tokens.primary,
                borderRadius: 2,
                transition: 'width 400ms ease-out',
              }}
            />
          </div>
        </div>

        {/* Stage rows */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <StageRow id="parsing" state={stages.parsing} />
          <StageRow id="extracting" state={stages.extracting} />
          <StageRow id="building_kg" state={stages.building_kg} />
        </div>

        {allDone && (
          <div
            style={{
              marginTop: 20,
              padding: '10px 16px',
              background: tokens.successSoft,
              border: `1px solid ${tokens.success}`,
              borderRadius: 8,
              color: tokens.success,
              fontSize: 12,
              textAlign: 'center',
              fontWeight: 500,
            }}
          >
            索引完成，正在加载问答界面…
          </div>
        )}
      </div>

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
