export type TaskItem = {
  id: number;
  task_type: string;
  label: string;
  status: 'pending' | 'running' | 'success' | 'failed';
  progress: number;
  stage: string;
  object_type: string;
  object_id: number | null;
  result: Record<string, unknown>;
  error: string;
  created_at: string;
  updated_at: string;
};

export type TaskListResponse = {
  summary: {
    total: number;
    active: number;
    has_active: boolean;
    by_status: Record<string, number>;
  };
  results: TaskItem[];
};

export type TaskStatusResponse = {
  tasks: TaskItem[];
  next_poll_after_ms: number;
};
