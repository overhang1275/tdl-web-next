export const queryKeys = {
  status: ["status"] as const,
  dashboard: ["dashboard"] as const,
  chats: (params: Record<string, string | number | boolean>) => ["chats", params] as const,
  chat: (id: string) => ["chat", id] as const,
  jobs: (params: Record<string, string | number>) => ["jobs", params] as const,
  job: (id: number) => ["job", id] as const,
  jobFiles: (id: number, params?: Record<string, string | number>) =>
    params ? ["job-files", id, params] as const : ["job-files", id] as const,
  jobLogs: (id: number) => ["job-logs", id] as const,
  jobEvents: (id: number) => ["job-events", id] as const,
  templates: ["templates"] as const,
  search: (q: string) => ["search", q] as const,
  settings: ["settings"] as const,
};
