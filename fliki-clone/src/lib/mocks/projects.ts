export type ProjectStatus = "draft" | "generating" | "done" | "error";

export interface Project {
  id: string;
  title: string;
  thumbnailColor: string;
  duration: string;
  status: ProjectStatus;
  updatedAt: string;
  scenes: number;
}

export const mockProjects: Project[] = [
  { id: "p1", title: "Product Launch Video", thumbnailColor: "#3b82f6", duration: "1:32", status: "done", updatedAt: "2 hours ago", scenes: 8 },
  { id: "p2", title: "Weekly News Roundup", thumbnailColor: "#a855f7", duration: "3:15", status: "done", updatedAt: "Yesterday", scenes: 12 },
  { id: "p3", title: "Tutorial: Getting Started", thumbnailColor: "#10b981", duration: "2:45", status: "generating", updatedAt: "Just now", scenes: 10 },
  { id: "p4", title: "Brand Story", thumbnailColor: "#ec4899", duration: "0:58", status: "draft", updatedAt: "3 days ago", scenes: 4 },
  { id: "p5", title: "Social Media Reel", thumbnailColor: "#f59e0b", duration: "0:30", status: "done", updatedAt: "1 week ago", scenes: 6 },
  { id: "p6", title: "Customer Testimonial", thumbnailColor: "#ef4444", duration: "1:10", status: "error", updatedAt: "2 days ago", scenes: 5 },
];
