import { request } from "@/api/client";

export interface LoginResponse {
    access_token: string;
    token_type: string;
}

export interface MeResponse {
    id: string;
    email: string;
    name: string | null;
    created_at: string;
}

export function login(email: string, password: string): Promise<LoginResponse> {
    return request<LoginResponse>("/api/auth/login", {
        method: "POST",
        body: { email, password },
    });
}

export function register(
    email: string,
    password: string,
    name: string | null,
): Promise<LoginResponse> {
    return request<LoginResponse>("/api/auth/register", {
        method: "POST",
        body: { email, password, name },
    });
}

export function me(): Promise<MeResponse> {
    return request<MeResponse>("/api/auth/me");
}