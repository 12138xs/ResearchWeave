import { Header } from '../../components/Header';
import { releaseNotes } from './notes';
import './releases.css';

export function ReleaseNotesView() {
  return <div className="release-notes-page">
    <Header eyebrow="运行管理" title="版本说明" description="每次交付记录实际修改，同时保留尚未完成的部分。记录随系统更新发布。" />
    <p className="release-notes-intro">当前系列：v0.5.0-preview.1 · 内部试用。以下补录已核实的近期上线记录，更早历史尚未完整整理。各条限制描述该次交付状态；后续修复会另列记录。</p>
    {releaseNotes.map((note, index) => <article className="release-note" key={note.id}>
      <div className="release-note-meta"><time dateTime={note.date}>{note.date}</time>{index === 0 && <span>最新修改</span>}<small>{note.reference}</small></div>
      <h2>{note.title}</h2>
      <ul>{note.changes.map((change) => <li key={change}>{change}</li>)}</ul>
      {note.limitations.length > 0 && <div className="release-note-limits"><h3>边界与待完善</h3><ul>{note.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>}
    </article>)}
  </div>;
}
