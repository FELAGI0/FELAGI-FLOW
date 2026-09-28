import { request } from "@/api/client";

export interface Credential {
    id: string;
    service: string;
    auth_type: string;
    name: string;
    created_at: string;
}

interface CredentialListResponse {
    items: Credential[];
}

export function listCredentials(wsId: string): Promise<Credential[]> {
    return request<CredentialListResponse>(`/api/workspaces/${wsId}/credentials`).then(
        (response) => response.items,
    );
}

export function createCredential(
    wsId: string,
    body: { service: string; name: string; payload: Record<string, string> },
): Promise<Credential> {
    return request<Credential>(`/api/workspaces/${wsId}/credentials`, {
        method: "POST",
        body,
    });
}

export function deleteCredential(wsId: string, credentialId: string): Promise<void> {
    return request<void>(`/api/workspaces/${wsId}/credentials/${credentialId}`, {
        method: "DELETE",
    });
}