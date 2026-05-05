import { create } from "zustand";

export type EditorPanel = "scenes" | "voice" | "media" | "captions";

interface EditorState {
  activeSceneId: string | null;
  activePanel: EditorPanel;
  isPlaying: boolean;
  zoom: number;
  setActiveScene: (id: string | null) => void;
  setActivePanel: (panel: EditorPanel) => void;
  togglePlay: () => void;
  setZoom: (zoom: number) => void;
  reset: () => void;
}

const initialState = {
  activeSceneId: null,
  activePanel: "scenes" as EditorPanel,
  isPlaying: false,
  zoom: 1,
};

export const useEditorStore = create<EditorState>((set) => ({
  ...initialState,
  setActiveScene: (activeSceneId) => set({ activeSceneId }),
  setActivePanel: (activePanel) => set({ activePanel }),
  togglePlay: () => set((s) => ({ isPlaying: !s.isPlaying })),
  setZoom: (zoom) => set({ zoom: Math.max(0.25, Math.min(4, zoom)) }),
  reset: () => set(initialState),
}));
