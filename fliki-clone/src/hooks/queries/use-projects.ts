"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { mockProjects, type Project } from "@/lib/mocks/projects";

const projectsKey = (filter?: { folderId?: string }) =>
  ["projects", filter ?? {}] as const;

async function fetchProjects(): Promise<Project[]> {
  await new Promise((r) => setTimeout(r, 300));
  return mockProjects;
}

async function deleteProject(id: string): Promise<{ id: string }> {
  await new Promise((r) => setTimeout(r, 200));
  return { id };
}

export function useProjectList(filter?: { folderId?: string }) {
  return useQuery({
    queryKey: projectsKey(filter),
    queryFn: fetchProjects,
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteProject,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useProjectJobStatus(jobId: string | null) {
  return useQuery({
    queryKey: ["job", jobId],
    enabled: !!jobId,
    queryFn: async () => {
      await new Promise((r) => setTimeout(r, 200));
      return { id: jobId!, status: "generating" as const, progress: 42 };
    },
    refetchInterval: (q) =>
      q.state.data && ["success", "error"].includes(q.state.data.status) ? false : 2000,
  });
}
