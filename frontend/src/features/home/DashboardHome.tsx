import { Link } from 'react-router-dom';

import { useApiData, useHealth } from '../../app/hooks';
import { Header } from '../../components/Header';
import { StatusPill } from '../../components/StatusPill';
import type { CatalogStats, KeywordEntry } from '../library/types';

const emptyStats: CatalogStats = {
  papers: 0,
  documents: 0,
  knowledge_spaces: 0,
  keywords: [],
  status_counts: {}
};

const defaultKeywords = ['PINN', 'Transformer', '算子学习', '反问题', 'Navier-Stokes'];

export function DashboardHome() {
  const health = useHealth();
  const { data: stats } = useApiData<CatalogStats>('/api/catalog/stats/', emptyStats);
  const { data: keywordLibrary } = useApiData<KeywordEntry[]>('/api/keywords/', []);
  const keywords = stats.keywords.length > 0 ? stats.keywords : defaultKeywords;
  const metrics = [
    { label: '论文资产', value: stats.papers, caption: '已完成结构化入库的研究论文' },
    { label: '知识文档', value: stats.documents, caption: '团队可复用的方法与经验沉淀' },
    { label: '知识体系', value: stats.knowledge_spaces, caption: '围绕研究主题组织的分类框架' },
    { label: '处理队列', value: health.status === 'ok' ? 3 : 0, caption: '粗读、精读与导入任务分队列执行' }
  ];

  return (
    <main className="page">
      <Header
        eyebrow="AI for PDEs"
        title="A510 研究知识库"
        description="面向 AI for PDEs 团队的研究资料管理平台，统一组织论文、知识文档、主题词与问答记录。"
      />

      <section className="metric-grid" aria-label="研究总览">
        {metrics.map((item) => (
          <article className="metric-card" key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
            <p>{item.caption}</p>
          </article>
        ))}
      </section>

      <section className="dashboard-grid">
        <article className="panel panel-wide">
          <div className="panel-title">
            <div>
              <p className="eyebrow">Processing Pipeline</p>
              <h2>论文处理流程</h2>
            </div>
            <StatusPill value={health.status} />
          </div>
          <div className="flow">
            {['安全上传', '元数据提取', 'AI 粗读', 'AI 精读', '审核归档'].map((step, index) => (
              <div className="flow-step" key={step}>
                <span>{index + 1}</span>
                <strong>{step}</strong>
              </div>
            ))}
          </div>
        </article>

        <article className="panel">
          <div className="panel-title">
            <div>
              <p className="eyebrow">Next Actions</p>
              <h2>继续研究</h2>
            </div>
          </div>
          <div className="quick-link-list">
            <Link to="/papers">继续阅读论文</Link>
            <Link to="/search">检索已有证据</Link>
            <Link to="/experiments">查看复现实验</Link>
          </div>
        </article>

        <article className="panel">
          <div className="panel-title">
            <div>
              <p className="eyebrow">Topics</p>
              <h2>高频主题</h2>
            </div>
          </div>
          <div className="tag-cloud">
            {keywords.map((keyword) => (
              <span key={keyword}>{keyword}</span>
            ))}
          </div>
        </article>
      </section>

      <section className="keyword-library-panel">
        <div className="panel-title">
          <div>
              <p className="eyebrow">Keyword Registry</p>
              <h2>主题词表</h2>
          </div>
          <span className="muted-inline">跨全库汇总</span>
        </div>
        {keywordLibrary.length === 0 ? (
          <p className="muted">论文和文档入库后，系统会持续维护统一主题词。</p>
        ) : (
          <div className="keyword-library-grid">
            {keywordLibrary.slice(0, 12).map((keyword) => (
              <article key={keyword.name}>
                <strong>{keyword.name}</strong>
                <span>{keyword.total_count} 条内容</span>
                {keyword.aliases.length > 0 && <p>别名：{keyword.aliases.join('、')}</p>}
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

