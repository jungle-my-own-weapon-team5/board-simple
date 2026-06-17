import { create } from "zustand";

type PostState = {
  query: string;
  contentQuery: string;
  tag: string;
  page: number;
  size: number;
  setFilters: (filters: { query: string; contentQuery: string; tag: string }) => void;
  setPage: (page: number) => void;
};

export const usePostStore = create<PostState>((set) => ({
  query: "",
  contentQuery: "",
  tag: "",
  page: 1,
  size: 10,
  setFilters: (filters) => set({ ...filters, page: 1 }),
  setPage: (page) => set({ page })
}));
