import { AlertCircle, Check, Loader2, X } from "lucide-react";

export type IngestJob = {
  id: string;
  title: string;
  status: "processing" | "success" | "error";
  message?: string;
};

type Props = {
  jobs: IngestJob[];
  onDismiss: (id: string) => void;
};

function statusLine(job: IngestJob) {
  if (job.status === "processing") return "已受理，正在解析与向量化…";
  if (job.status === "success") return "已入库，知识空间已更新";
  return job.message || "入库失败";
}

export default function IngestToastStack({ jobs, onDismiss }: Props) {
  if (jobs.length === 0) return null;

  return (
    <div className="ingest-toast-stack" aria-live="polite" aria-label="入库进度">
      {jobs.map((job) => (
        <div key={job.id} className={`ingest-toast ingest-toast--${job.status}`} role="status">
          <div className="ingest-toast-icon" aria-hidden>
            {job.status === "processing" && <Loader2 size={16} className="spin" />}
            {job.status === "success" && <Check size={16} />}
            {job.status === "error" && <AlertCircle size={16} />}
          </div>
          <div className="ingest-toast-body">
            <strong>{job.title}</strong>
            <span>{statusLine(job)}</span>
          </div>
          {job.status === "processing" && <div className="ingest-toast-bar" aria-hidden />}
          {job.status !== "processing" && (
            <button
              type="button"
              className="ingest-toast-dismiss"
              onClick={() => onDismiss(job.id)}
              aria-label="关闭"
            >
              <X size={14} />
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
