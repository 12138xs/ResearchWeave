import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { createExperiment, fetchExperiments } from '../../api/experiments';
import { createPaperReadingReview, fetchPaperReadingReviews, fetchPaperReadingState, patchPaperReadingState } from '../../api/papers';
import type { ExperimentListResponse } from '../experiments/types';
import type { Paper, PaperReadingState, ReadingReview } from './types';

const readingLabels: Record<PaperReadingState['reading_status'], string> = {
  unread: '未读',
  skimmed: '已粗读',
  deep_reading: '深读中',
  discussed: '已讨论',
  adopted: '已采用',
  rejected: '已排除'
};

const reproductionLabels: Record<PaperReadingState['reproduction_status'], string> = {
  unknown: '未知',
  not_applicable: '不适用',
  planned: '已计划',
  in_progress: '进行中',
  reproduced: '已复现',
  failed: '复现失败'
};

const reviewLabels: Record<ReadingReview['status'], string> = {
  needs_review: '待复核',
  approved: '已通过',
  rejected: '已驳回'
};

export function PaperReadingPanel({ paper }: { paper: Paper }) {
  const [state, setState] = useState<PaperReadingState | null>(paper.reading_state ?? null);
  const [experiments, setExperiments] = useState<ExperimentListResponse['results']>([]);
  const [reviews, setReviews] = useState<ReadingReview[]>([]);
  const [nextStep, setNextStep] = useState(paper.reading_state?.next_step ?? '');
  const [dueAt, setDueAt] = useState('');
  const [reviewNotes, setReviewNotes] = useState('');
  const [reviewScore, setReviewScore] = useState('80');
  const [message, setMessage] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let mounted = true;
    fetchPaperReadingState(paper.id).then((payload) => {
      if (mounted) setState(payload as PaperReadingState);
    });
    fetchExperiments(`/api/experiments/?paper=${paper.id}`).then((payload) => {
      if (mounted) setExperiments(((payload as ExperimentListResponse).results ?? []));
    });
    fetchPaperReadingReviews(paper.id).then((payload) => {
      if (mounted) setReviews((payload as ReadingReview[]) ?? []);
    });
    return () => {
      mounted = false;
    };
  }, [paper.id]);

  const updateState = async (payload: Partial<PaperReadingState>) => {
    setSaving(true);
    const next = await patchPaperReadingState(paper.id, payload);
    setState(next as PaperReadingState);
    setSaving(false);
  };

  const saveNextStep = async () => {
    setMessage('');
    await updateState({
      next_step: nextStep,
      due_at: dueAt ? new Date(dueAt).toISOString() : null
    });
    setMessage('阅读计划已保存。');
  };

  const reviewProfile = async (profileType: 'light' | 'deep', profileId: number, status: 'approved' | 'rejected') => {
    setSaving(true);
    setMessage('');
    const payload = await createPaperReadingReview(paper.id, {
      profile_type: profileType,
      profile_id: profileId,
      status,
      score: Number(reviewScore) || null,
      notes: reviewNotes
    });
    setReviews((current) => [payload as ReadingReview, ...current]);
    setMessage(status === 'approved' ? '复核已通过。' : '复核已驳回。');
    setSaving(false);
  };

  const createReproductionProject = async () => {
    setSaving(true);
    setMessage('');
    const payload = await createExperiment({
      title: `复现：${paper.title}`,
      paper: paper.id,
      space: paper.space_id ?? null,
      status: 'planned',
      objective: `复现并核对《${paper.title}》的核心方法、指标和可复用结论。`,
      protocol_markdown: `# 复现实验计划\n\n## 目标\n复现《${paper.title}》的关键方法。\n\n## 下一步\n- 阅读实验设置\n- 确认数据与代码\n- 记录参数和指标\n`
    });
    const experiment = payload as ExperimentListResponse['results'][number];
    setExperiments((current) => [experiment, ...current]);
    await updateState({ reproduction_status: 'planned', next_step: nextStep || '建立复现实验项目并补充实验协议。' });
    setMessage('复现实验项目已创建。');
    setSaving(false);
  };

  const dueLabel = state?.due_at ? formatPanelDate(state.due_at) : '未设置';

  return (
    <article className="reading-workflow-panel">
      <div className="reading-panel-header">
        <div>
          <p className="eyebrow">Workflow</p>
          <h2>阅读与复现</h2>
          <p className="reading-panel-copy">跟踪负责人、下一步、复现状态和人工复核。</p>
        </div>
        <button type="button" className="secondary-button" onClick={createReproductionProject} disabled={saving}>
          创建复现实验
        </button>
      </div>

      {state ? (
        <section className="reading-status-grid" aria-label="阅读状态摘要">
          <div>
            <span>阅读状态</span>
            <strong>{readingLabels[state.reading_status]}</strong>
          </div>
          <div>
            <span>复现状态</span>
            <strong>{reproductionLabels[state.reproduction_status]}</strong>
          </div>
          <div>
            <span>负责人</span>
            <strong>{state.owner_username || '未指定'}</strong>
          </div>
          <div>
            <span>截止时间</span>
            <strong>{dueLabel}</strong>
          </div>
        </section>
      ) : (
        <p className="muted">正在读取阅读状态...</p>
      )}

      {state && (
        <section className="reading-subpanel">
          <div className="reading-subpanel-title">
            <div>
              <h3>下一步计划</h3>
              <p>{state.next_step || '还没有记录下一步。'}</p>
            </div>
            <div className="reading-status-controls">
              <label>
                <span>阅读</span>
                <select
                  value={state.reading_status}
                  disabled={saving}
                  onChange={(event) => updateState({ reading_status: event.target.value as PaperReadingState['reading_status'] })}
                >
                  {Object.entries(readingLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              <label>
                <span>复现</span>
                <select
                  value={state.reproduction_status}
                  disabled={saving}
                  onChange={(event) => updateState({ reproduction_status: event.target.value as PaperReadingState['reproduction_status'] })}
                >
                  {Object.entries(reproductionLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
            </div>
          </div>
          <div className="reading-plan-grid">
            <label>
              <span>下一步</span>
              <textarea value={nextStep} onChange={(event) => setNextStep(event.target.value)} placeholder="例如：核对实验设置，准备组会讨论，补充复现数据集。" />
            </label>
            <label>
              <span>截止时间</span>
              <input type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} />
            </label>
          </div>
          <div className="reading-save-row">
            <button type="button" className="secondary-button" onClick={saveNextStep} disabled={saving}>
              保存阅读计划
            </button>
          </div>
        </section>
      )}

      <section className="reading-subpanel">
        <div className="reading-subpanel-title">
          <div>
            <h3>人工复核</h3>
          </div>
        </div>
        <div className="review-input-row">
          <label>
            <span>评分</span>
            <input value={reviewScore} onChange={(event) => setReviewScore(event.target.value)} />
          </label>
          <label>
            <span>备注</span>
            <input value={reviewNotes} onChange={(event) => setReviewNotes(event.target.value)} placeholder="复核意见" />
          </label>
        </div>
        <div className="review-action-grid">
          {paper.light_profile && (
            <div className="review-action-card">
              <span>粗读复核</span>
              <div className="review-action-buttons">
                <button type="button" className="secondary-button" disabled={saving} onClick={() => reviewProfile('light', paper.light_profile!.id, 'approved')}>通过</button>
                <button type="button" className="secondary-button" disabled={saving} onClick={() => reviewProfile('light', paper.light_profile!.id, 'rejected')}>驳回</button>
              </div>
            </div>
          )}
          {paper.deep_profile && (
            <div className="review-action-card">
              <span>精读复核</span>
              <div className="review-action-buttons">
                <button type="button" className="secondary-button" disabled={saving} onClick={() => reviewProfile('deep', paper.deep_profile!.id, 'approved')}>通过</button>
                <button type="button" className="secondary-button" disabled={saving} onClick={() => reviewProfile('deep', paper.deep_profile!.id, 'rejected')}>驳回</button>
              </div>
            </div>
          )}
          {!paper.light_profile && !paper.deep_profile && <p className="muted">生成粗读或精读后可进行人工复核。</p>}
        </div>
        {reviews.length > 0 && (
          <div className="review-history">
            {reviews.slice(0, 3).map((review) => (
              <div key={review.id}>
                <span>{review.profile_type === 'deep' ? '精读' : '粗读'} · {reviewLabels[review.status]}</span>
                <strong>{review.score ?? '未评分'}</strong>
                {review.reviewed_by_username && <small>{review.reviewed_by_username}</small>}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="reading-subpanel">
        <div className="reading-subpanel-title">
          <div>
            <h3>关联实验</h3>
          </div>
        </div>
        <div className="linked-experiment-list">
          {experiments.map((experiment) => (
            <Link key={experiment.id} to={`/experiments/${experiment.id}`}>
              <span>{experiment.title}</span>
              <strong>打开</strong>
            </Link>
          ))}
          {experiments.length === 0 && <p className="muted">暂无关联复现实验。</p>}
        </div>
      </section>

      {message && <p className="form-message">{message}</p>}
    </article>
  );
}

function formatPanelDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '未设置';
  return date.toLocaleDateString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  });
}
