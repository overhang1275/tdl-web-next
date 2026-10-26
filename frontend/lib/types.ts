export type JobStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type JobStage =
  | "pending"
  | "exporting"
  | "filtering"
  | "downloading"
  | "completed"
  | "failed"
  | "cancelled";

export interface Page<T> {
  items: T[];
  page: number;
  per_page: number;
  total: number;
  page_count: number;
}

export interface Job {
  id: number;
  chat_id: string;
  chat_title: string | null;
  hashtag: string | null;
  media_type: string;
  search_text: string | null;
  date_from: string | null;
  date_to: string | null;
  skip_same: boolean;
  refresh_export: boolean;
  export_only: boolean;
  output_subfolder: string;
  status: JobStatus;
  stage: JobStage;
  total_filtered_messages: number;
  total_downloaded_files: number;
  total_failed_files: number;
  transfer_initialized: boolean;
  downloaded_bytes: number;
  total_expected_bytes: number | null;
  speed_bps: number;
  eta_seconds: number | null;
  progress_percent: number | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  queue_position: number | null;
  deletion_requested: boolean;
  deletion_error: string | null;
}

export interface JobFile {
  file_id: number | null;
  message_id: string | null;
  name: string;
  relative_path: string;
  size: number;
  human_size: string;
  kind: string;
  modified_at: number;
  modified_label: string;
  can_preview: boolean;
  status: string | null;
  attempts: number;
  last_error: string | null;
  content_url: string;
  download_url: string;
}

export interface Chat {
  id: string;
  title: string;
  username: string;
  type: string;
  topics_count: number;
}

export interface ChatPage extends Page<Chat> {
  q: string;
  chat_type: string;
  sort: string;
  type_counts: Record<string, number>;
  cached_at: string | null;
  refreshed: boolean;
}

export interface ChatProfile {
  chat: Chat | null;
  chat_id: string;
  chat_title: string;
  jobs: Job[];
  export_exists: boolean;
  export_updated_at: string | null;
  downloaded_files: number;
  downloaded_size: string;
  download_root: string;
}

export interface Status {
  environment: string;
  version: string;
  session_active: boolean;
  session_error: string | null;
  tdl_installed: boolean;
  tdl_binary: string;
  redis_connected: boolean;
  redis_error: string | null;
  worker_connected: boolean;
  worker_count: number;
  storage: string;
  can_start_services: boolean;
  authentik_configured: boolean;
}

export interface Dashboard {
  active_jobs: number;
  failed_jobs: number;
  downloaded_files: number;
  disk_usage: string;
  latest_errors: Job[];
  chat_counts: {
    channels: number;
    groups: number;
    private: number;
    total: number;
    cached_at: string | null;
  };
}

export interface Template {
  id: number;
  name: string;
  chat_id: string | null;
  chat_title: string | null;
  hashtag: string | null;
  media_type: string;
  search_text: string | null;
  date_from: string | null;
  date_to: string | null;
  skip_same: boolean;
  refresh_export: boolean;
  export_only: boolean;
  output_subfolder: string | null;
  created_at: string;
}

export interface SearchItem {
  id: string | number;
  title: string;
  subtitle: string;
  url: string;
  download_url?: string | null;
}

export interface SearchResult {
  chats: SearchItem[];
  jobs: SearchItem[];
  files: SearchItem[];
}

export interface JobCreate {
  chat_id: string;
  chat_title?: string | null;
  hashtag?: string | null;
  media_type: string;
  search_text?: string | null;
  date_from?: string | null;
  date_to?: string | null;
  skip_same: boolean;
  refresh_export: boolean;
  export_only: boolean;
  output_subfolder: string;
}

export interface EventItem {
  title: string;
  timestamp: string;
  message: string;
}

export interface LogResult {
  content: string;
  truncated: boolean;
}
