import { create } from "zustand";

/**
 * Access-токен живёт только в памяти (не localStorage): refresh хранится в
 * httpOnly-cookie, поэтому перезагрузка страницы восстанавливает сессию через
 * POST /api/auth/refresh, а не через чтение хранилища.
 */
interface AuthState {
    accessToken: string | null;
    setAccessToken: (token: string | null) => void;
    clear: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
    accessToken: null,
    setAccessToken: (token) => set({ accessToken: token }),
    clear: () => set({ accessToken: null }),
}));