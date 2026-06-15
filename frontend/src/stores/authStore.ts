import { create } from "zustand";
import * as authApi from "../api/auth";
import { ApiError } from "../api/client";
import type { User } from "../types";

type AuthState = {
  user: User | null;
  isLoading: boolean;
  error: string | null;
  bootstrap: () => Promise<void>;
  setUser: (user: User) => void;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, nickname?: string) => Promise<void>;
  logout: () => Promise<void>;
};

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isLoading: true,
  error: null,
  setUser: (user) => set({ user, error: null }),
  bootstrap: async () => {
    try {
      const user = await authApi.getMe();
      set({ user, error: null });
    } catch (error) {
      if (error instanceof ApiError && error.status !== 401) {
        set({ error: error.message });
      }
      set({ user: null });
    } finally {
      set({ isLoading: false });
    }
  },
  login: async (email, password) => {
    await authApi.login({ email, password });
    const user = await authApi.getMe();
    set({ user, error: null });
  },
  register: async (email, password, nickname) => {
    await authApi.register({ email, password, nickname: nickname || undefined });
    await authApi.login({ email, password });
    const user = await authApi.getMe();
    set({ user, error: null });
  },
  logout: async () => {
    await authApi.logout();
    set({ user: null });
  }
}));
