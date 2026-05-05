export interface Template {
  id: string;
  title: string;
  category: string;
  thumbnailColor: string;
  duration: string;
  language: string;
  uses: number;
}

export const templateCategories = [
  "All", "YouTube", "TikTok", "Instagram", "Podcast",
  "Marketing", "Education", "News", "Business", "E-learning",
];

export const mockTemplates: Template[] = [
  { id: "t1",  title: "Product Demo",           category: "YouTube",    thumbnailColor: "#3b82f6",   duration: "1:00", language: "English", uses: 12400 },
  { id: "t2",  title: "Explainer Video",         category: "Education",  thumbnailColor: "#a855f7",   duration: "2:00", language: "English", uses: 8900  },
  { id: "t3",  title: "Vertical Reel",           category: "TikTok",     thumbnailColor: "#ec4899",   duration: "0:30", language: "English", uses: 22000 },
  { id: "t4",  title: "News Summary",            category: "News",       thumbnailColor: "#f59e0b",   duration: "1:30", language: "English", uses: 5600  },
  { id: "t5",  title: "Tutorial Walkthrough",    category: "E-learning", thumbnailColor: "#10b981",   duration: "3:00", language: "English", uses: 7100  },
  { id: "t6",  title: "Story Ad",                category: "Instagram",  thumbnailColor: "#ef4444",   duration: "0:15", language: "English", uses: 15300 },
  { id: "t7",  title: "Corporate Update",        category: "Business",   thumbnailColor: "#64748b",   duration: "2:30", language: "English", uses: 3400  },
  { id: "t8",  title: "Podcast Intro",           category: "Podcast",    thumbnailColor: "#8b5cf6",   duration: "0:45", language: "English", uses: 9800  },
  { id: "t9",  title: "How-To Guide",            category: "E-learning", thumbnailColor: "#14b8a6",   duration: "2:00", language: "English", uses: 11200 },
  { id: "t10", title: "YouTube Shorts",          category: "YouTube",    thumbnailColor: "#f43f5e",   duration: "0:55", language: "English", uses: 18600 },
  { id: "t11", title: "Brand Story",             category: "Marketing",  thumbnailColor: "#f97316",   duration: "1:20", language: "English", uses: 6700  },
  { id: "t12", title: "Instagram Carousel",      category: "Instagram",  thumbnailColor: "#d946ef",   duration: "0:20", language: "English", uses: 13400 },
];
