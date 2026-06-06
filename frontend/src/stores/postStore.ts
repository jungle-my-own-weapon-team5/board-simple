import { create } from "zustand";

type PostState = {
  query: string;
  page: number;
  size: number;
  setQuery: (query: string) => void;
  setPage: (page: number) => void;
};

export const usePostStore = create<PostState>((set) => ({
  query: "",
  page: 1,
  size: 10,
  setQuery: (query) => set({ query, page: 1 }),
  setPage: (page) => set({ page })
}));
