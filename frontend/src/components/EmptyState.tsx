export function EmptyState({ title, note }: { title: string; note: string }) {
  return (
    <div className="empty-state">
      <div className="empty-mark">空</div>
      <h3>{title}</h3>
      <p>{note}</p>
    </div>
  );
}


