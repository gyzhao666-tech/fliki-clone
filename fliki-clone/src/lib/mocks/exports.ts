export type ExportJob = {
  id: string;
  title: string;
  format: "MP4" | "MP3" | "MOV";
  status: "ready" | "processing" | "failed";
  createdAt: string;
  size: string;
};

export const mockExports: ExportJob[] = [
  { id: "e1", title: "Product Launch Video", format: "MP4", status: "ready", createdAt: "2 hours ago", size: "12.4 MB" },
  { id: "e2", title: "Q1 Social Pack", format: "MP4", status: "ready", createdAt: "Yesterday", size: "48.1 MB" },
  { id: "e3", title: "Podcast intro", format: "MP3", status: "processing", createdAt: "Just now", size: "—" },
];
