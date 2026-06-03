import { type FormEvent, useState } from 'react';

import { apiFetch, payloadMessage, readResponsePayload } from '../../api/client';
import { Header } from '../../components/Header';

export function UploadPaper() {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [year, setYear] = useState('');
  const [venue, setVenue] = useState('');
  const [area, setArea] = useState('');
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const submitUpload = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setMessage('');
    setError('');
    if (!file) {
      setError('请先选择 PDF 文件。');
      return;
    }

    const formData = new FormData();
    formData.append('file', file);
    if (title.trim()) formData.append('title', title.trim());
    if (year.trim()) formData.append('year', year.trim());
    if (venue.trim()) formData.append('venue', venue.trim());
    if (area.trim()) formData.append('area', area.trim());

    setUploading(true);
    try {
      const response = await apiFetch('/api/papers/upload/', {
        method: 'POST',
        body: formData
      });
      const payload = await readResponsePayload(response);
      if (!response.ok) {
        throw new Error(payloadMessage(payload, '上传失败，请检查文件格式。'));
      }
      setMessage(`已上传《${payload.title}》，论文已进入目录，后续可触发轻量解读。`);
      setFile(null);
      setTitle('');
      setYear('');
      setVenue('');
      setArea('');
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : '上传失败，请稍后重试。');
    } finally {
      setUploading(false);
    }
  };

  return (
    <main className="page">
      <Header
        eyebrow="Paper Ingestion"
        title="上传论文"
        description="上传 PDF 后自动建立论文记录，抽取元数据与主题词，并触发 AI 粗读；后续可按需启动 AI 精读。"
      />
      <section className="upload-zone upload-form-zone">
        <form className="upload-form" onSubmit={submitUpload}>
          <label>
            PDF 文件
            <input
              accept="application/pdf,.pdf"
              type="file"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <label>
            论文标题
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="留空将自动从 PDF/元数据补全，不再使用文件名作为标题"
            />
          </label>
          <div className="form-grid">
            <label>
              年份
              <input value={year} onChange={(event) => setYear(event.target.value)} placeholder="例如 2024" />
            </label>
            <label>
              期刊/会议
              <input value={venue} onChange={(event) => setVenue(event.target.value)} placeholder="例如 NeurIPS" />
            </label>
          </div>
          <label>
            方向
            <input value={area} onChange={(event) => setArea(event.target.value)} placeholder="例如 PINN / Neural Operator" />
          </label>
          <button type="submit" disabled={uploading}>
            {uploading ? '上传中' : '上传到论文库'}
          </button>
        </form>
        {(message || error) && (
          <div className={error ? 'form-message form-message-error' : 'form-message'}>
            {error || message}
          </div>
        )}
        <p>当前只做文件校验、检疫区保存和目录登记；不会立刻启动重型解析任务。</p>
      </section>
    </main>
  );
}


