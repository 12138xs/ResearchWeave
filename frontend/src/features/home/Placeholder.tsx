import { Header } from '../../components/Header';

export function Placeholder({ title }: { title: string }) {
  return (
    <main className="page">
      <Header eyebrow="工作区" title={title} description="这个页面已经预留，下一阶段会接入真实数据和操作流程。" />
    </main>
  );
}
