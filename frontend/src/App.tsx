import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Navigate, Route, BrowserRouter as Router, Routes } from "react-router-dom";

import { PrivateRoute } from "@/components/PrivateRoute";
import { ToastProvider } from "@/components/ui/toast";
import { EditorPage } from "@/editor/EditorPage";
import { LoginPage } from "@/pages/LoginPage";
import { WorkflowListPage } from "@/pages/WorkflowListPage";
import { WorkspaceListPage } from "@/pages/WorkspaceListPage";

const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

export function App() {
    return (
        <QueryClientProvider client={queryClient}>
            <ToastProvider>
                <Router>
                    <Routes>
                        <Route path="/login" element={<LoginPage />} />
                        <Route
                            path="/workspaces"
                            element={
                                <PrivateRoute>
                                    <WorkspaceListPage />
                                </PrivateRoute>
                            }
                        />
                        <Route
                            path="/workspaces/:wsId/workflows"
                            element={
                                <PrivateRoute>
                                    <WorkflowListPage />
                                </PrivateRoute>
                            }
                        />
                        <Route
                            path="/workspaces/:wsId/workflows/:wfId/edit"
                            element={
                                <PrivateRoute>
                                    <EditorPage />
                                </PrivateRoute>
                            }
                        />
                        <Route path="*" element={<Navigate to="/workspaces" replace />} />
                    </Routes>
                </Router>
            </ToastProvider>
        </QueryClientProvider>
    );
}