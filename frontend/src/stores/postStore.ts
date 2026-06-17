import { create } from "zustand";

type PostState = {
  query: string;
  page: number;
  size: number;
  resetSearchToken: number;
  resetSearch: () => void;
  setQuery: (query: string) => void;
  setPage: (page: number) => void;
};

export const usePostStore = create<PostState>((set) => ({
  query: "",
  page: 1,
  size: 10,
  resetSearchToken: 0,
  resetSearch: () => set((state) => ({ query: "", page: 1, resetSearchToken: state.resetSearchToken + 1 })),
  setQuery: (query) => set({ query, page: 1 }),
  setPage: (page) => set({ page })
}));
