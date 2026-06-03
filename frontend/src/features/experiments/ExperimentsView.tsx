import { Link, useParams } from 'react-router-dom';
import { useState } from 'react';

import { createExperiment, createExperimentRun, executeExperimentRun } from '../../api/experiments';
import { Header } from '../../components/Header';
import { StatusPill } from '../../components/StatusPill';
import { useApiData } from '../../app/hooks';
import type { ExperimentListResponse, ExperimentProject, ExperimentRun } from './types';

const emptyExperiments: ExperimentListResponse = {
  count: 0,
  page: 1,
  page_size: 25,
  total_pages: 1,
  results: []
};

export function ExperimentsView() {
  const [reload, setReload] = useState(0);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState('');
  const [objective, setObjective] = useState('');
  const [message, setMessage] = useState('');
  const { data, loading, error } = useApiData<ExperimentListResponse>(`/api/experiments/?reload=${reload}`, emptyExperiments);
  const submit = async () => {
    if (!title.trim()) return;
    setMessage('');
    const payload = await createExperiment({
      title: title.trim(),
      status: 'planned',
      objective,
      protocol_markdown: `# ${title.trim()}\n\n## 目标\n${objective || '待补充'}\n\n## 实验协议\n- 记录数据、环境和参数\n- 运行实验\n- 汇总指标\n`
    });
    setTitle('');
    setObjective('');
    setShowCreate(false);
    setMessage(`已创建实验项目：${(payload as ExperimentProject).title}`);
    setReload((value) => value + 1);
  };
  return (
    <main className="page experiments-page">
      <Header eyebrow="" title="实验与复现" description="记录复现项目、运行过程和结果线索。" />
      <section className="experiments-workbench">
        <div className="experiment-toolbar">
          <div>
            <strong>复现项目</strong>
            <span>按论文、目标和运行记录追踪实验进展。</span>
          </div>
          <div className="inline-actions">
            <button type="button" onClick={() => setShowCreate((value) => !value)}>
              {showCreate ? '收起创建' : '新建实验项目'}
            </button>
            <Link className="secondary-button link-button" to="/papers">从论文选择</Link>
          </div>
        </div>
        {showCreate && (
          <article className="experiment-create-panel">
            <h2>新建实验项目</h2>
            <label>
              <span>标题</span>
              <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：复现 PINNsFormer 核心实验" />
            </label>
            <label>
              <span>目标</span>
              <textarea value={objective} onChange={(event) => setObjective(event.target.value)} placeholder="实验目标、对照指标、验证问题或预期结论" />
            </label>
            <div className="experiment-create-actions">
              <button type="button" onClick={submit} disabled={!title.trim()}>创建项目</button>
              <button type="button" className="secondary-button" onClick={() => setShowCreate(false)}>取消</button>
            </div>
            {message && <p className="form-message">{message}</p>}
          </article>
        )}
        {!showCreate && message && <p className="form-message">{message}</p>}
      </section>
      {loading && <p className="muted">正在读取实验记录...</p>}
      {error && <p className="error-text">实验记录暂时无法读取。</p>}
      <section className="experiment-project-list" aria-label="实验项目列表">
        {data.results.map((experiment) => (
          <article className="experiment-project-row" key={experiment.id}>
            <div className="card-header">
              <div>
                <p className="eyebrow">{experiment.space_path || '未归档'}</p>
                <h2><Link to={`/experiments/${experiment.id}`}>{experiment.title}</Link></h2>
              </div>
              <StatusPill value={experiment.status} />
            </div>
            <p>{experiment.objective || '暂无实验目标。'}</p>
            <div className="experiment-row-meta">
              {experiment.paper_title && <span>关联论文：{experiment.paper_title}</span>}
              <Link to={`/experiments/${experiment.id}`}>查看详情</Link>
            </div>
          </article>
        ))}
        {!loading && data.results.length === 0 && (
          <article className="search-empty-state">
            <h2>还没有实验项目</h2>
            <p>可以从左侧创建一个人工记录项目，或进入论文详情创建关联复现项目。</p>
          </article>
        )}
      </section>
    </main>
  );
}

export function ExperimentDetailView() {
  const { id } = useParams();
  const [reload, setReload] = useState(0);
  const [runNotes, setRunNotes] = useState('');
  const [message, setMessage] = useState('');
  const { data: experiment, loading, error } = useApiData<ExperimentProject | null>(
    id ? `/api/experiments/${id}/?reload=${reload}` : '',
    null
  );
  const addRun = async () => {
    if (!experiment) return;
    const payload = await createExperimentRun(experiment.id, { notes: runNotes, status: 'planned' });
    setRunNotes('');
    setMessage(`已添加运行记录 #${(payload as ExperimentRun).id}`);
    setReload((value) => value + 1);
  };
  const executeRun = async (run: ExperimentRun) => {
    const payload = await executeExperimentRun(run.id);
    setMessage(payload?.task ? `执行任务已加入队列：T${String(payload.task.id).padStart(4, '0')}` : '执行任务提交失败。');
    setReload((value) => value + 1);
  };
  return (
    <main className="page experiments-page">
      <Header eyebrow="" title={experiment?.title || '实验详情'} description="复现协议、运行参数、指标与产物线索。" />
      {loading && <p className="muted">正在读取实验详情...</p>}
      {error && <p className="error-text">实验详情暂时无法读取。</p>}
      {experiment && (
        <section className="experiment-detail-grid">
          <article className="experiment-main-panel">
            <div className="panel-title">
              <div>
                <p className="eyebrow">{experiment.space_path || '未归档'}</p>
                <h2>{experiment.title}</h2>
              </div>
              <StatusPill value={experiment.status} />
            </div>
            <p>{experiment.objective || '暂无实验目标。'}</p>
            <RichBlock title="复现实验协议" content={experiment.protocol_markdown || '暂无协议。'} />
          </article>

          <aside className="experiment-run-panel">
            <h2>运行记录</h2>
            <label>
              <span>新增 run</span>
              <textarea value={runNotes} onChange={(event) => setRunNotes(event.target.value)} placeholder="本次运行说明、参数、环境或指标备注" />
            </label>
            <button type="button" onClick={addRun}>添加 run</button>
            {message && <p className="form-message">{message}</p>}
            <div className="experiment-run-list">
              {(experiment.runs ?? []).map((run) => (
                <div className="experiment-run-row" key={run.id}>
                  <div>
                    <StatusPill value={run.status} />
                    <p>{run.notes || `Run #${run.id}`}</p>
                  </div>
                  {run.status === 'planned' && <button type="button" className="secondary-button" onClick={() => executeRun(run)}>执行</button>}
                </div>
              ))}
              {(experiment.runs ?? []).length === 0 && <p className="muted">暂无运行记录。</p>}
            </div>
          </aside>
        </section>
      )}
    </main>
  );
}

function RichBlock({ title, content }: { title: string; content: string }) {
  return (
    <section className="experiment-protocol-panel">
      <h3>{title}</h3>
      <pre className="source-preview">{content}</pre>
    </section>
  );
}
