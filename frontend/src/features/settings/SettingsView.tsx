import { Header } from '../../components/Header';
import { useHealth } from '../../app/hooks';

export function SettingsView() {
  const health = useHealth();
  const release = health.release;
  const publicOrigin = typeof window !== 'undefined' ? window.location.origin : 'PUBLIC_BASE_URL';

  return (
    <main className="page">
      <Header
        eyebrow="System"
        title="系统设置"
        description="记录部署入口、运行边界与维护策略，确保内部服务安全、可恢复、可交接。"
      />
      <section className="settings-list">
        <div><span>系统版本</span><strong>{release ? `${release.product} ${release.version}` : '读取中'}</strong></div>
        <div><span>发布日期</span><strong>{release?.released_at || '读取中'}</strong></div>
        <div><span>迁移状态</span><strong>{release?.migration_state || '读取中'}</strong></div>
        <div><span>访问入口</span><strong>{publicOrigin}</strong></div>
        <div><span>Docker 子网</span><strong>10.89.0.0/24</strong></div>
        <div><span>唯一写入源</span><strong>Django / PostgreSQL</strong></div>
        <div><span>导出形式</span><strong>Markdown 快照</strong></div>
      </section>
      {release && (
        <section className="detail-card">
          <h2>发布说明</h2>
          <p>{release.summary}</p>
        </section>
      )}
    </main>
  );
}
