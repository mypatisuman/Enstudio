import React, { useEffect } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

import { AuthProvider, useAuth } from "./contexts/AuthContext";
import { fetchCsrfToken } from "./components/AIRecommender/api";
import ServerStatusBanner from "./components/ServerStatusBanner";

import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import Index from "./pages/Index";
import Project from "./pages/Project";
import Chat from "./pages/Chat";
import Catalog from "./pages/Catalog";

import AdminDashboard from "./pages/AdminDashboard";
import UtilizationPage from "./pages/UtilizationPage";
import CreditsPage from "./pages/CreditsPage";
import Assets from "./pages/Assets";
import AssetConfiguration from "./pages/AssetConfiguration";
import Benchmarks from "./pages/Benchmarks";
import PIDStudioPage from "./pages/PIDStudioPage";
import PIDHomeScreen from "./pages/pid/PIDHomeScreen";
import PIDIngestPage from "./pages/pid/PIDIngestPage";
import PIDReviewPage from "./pages/pid/PIDReviewPage";
import PIDCanvasPage from "./pages/pid/PIDCanvasPage";
import PIDDescribePage from "./pages/pid/PIDDescribePage";
import PIDValidationPage from "./pages/pid/PIDValidationPage";
import PIDExportPage from "./pages/pid/PIDExportPage";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

/* =========================
   Protected Route
   ========================= */
interface ProtectedRouteProps {
  children: React.ReactNode;
  requireAdmin?: boolean;
}

const ProtectedRoute = ({
  children,
  requireAdmin = false,
}: ProtectedRouteProps) => {
  const { isAuthenticated, isLoading, user } = useAuth();

  // Prevent redirect until auth is resolved with clean themed spinner
  if (isLoading) {
    return (
      <div className="flex h-screen w-full flex-col items-center justify-center bg-slate-950 text-slate-400">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-sky-500 border-t-transparent" />
          <span className="text-xs font-medium text-slate-400">Loading Workspace...</span>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (requireAdmin && user?.role !== "admin") {
    return <Navigate to="/chat" replace />;
  }

  return <>{children}</>;
};

/* =========================
   App
   ========================= */
const App = () => {
  useEffect(() => {
    fetchCsrfToken().catch((error) => {
      console.error('[App] Failed to initialize CSRF token:', error);
    });
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <AuthProvider>
          <Toaster />
          <Sonner />
          <ServerStatusBanner />

          <Routes>
            {/* Public routes */}
            <Route path="/" element={<Landing />} />
            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />

            {/* Primary Describe Agent Workflow routes (promoted to primary application page) */}
            <Route
              path="/chat"
              element={
                <ProtectedRoute>
                  <PIDDescribePage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/describe"
              element={
                <ProtectedRoute>
                  <PIDDescribePage />
                </ProtectedRoute>
              }
            />

            {/* Legacy Product Recommender Chat */}
            <Route
              path="/recommender"
              element={
                <ProtectedRoute>
                  <Chat />
                </ProtectedRoute>
              }
            />
            <Route
              path="/legacy-chat"
              element={
                <ProtectedRoute>
                  <Chat />
                </ProtectedRoute>
              }
            />

            <Route
              path="/chat/admin"
              element={
                <ProtectedRoute requireAdmin>
                  <AdminDashboard />
                </ProtectedRoute>
              }
            />

            {/* Workspace / App alias */}
            <Route
              path="/app"
              element={
                <ProtectedRoute>
                  <Navigate to="/chat" replace />
                </ProtectedRoute>
              }
            />

            {/* Solution routes */}
            <Route
              path="/solution"
              element={
                <ProtectedRoute>
                  <Project />
                </ProtectedRoute>
              }
            />
            <Route
              path="/solution/pid-viewer"
              element={
                <ProtectedRoute>
                  <PIDStudioPage />
                </ProtectedRoute>
              }
            />

            {/* P&ID Studio Suite Routes */}
            <Route
              path="/pid-studio"
              element={
                <ProtectedRoute>
                  <PIDHomeScreen />
                </ProtectedRoute>
              }
            />
            <Route
              path="/pid-studio/dashboard"
              element={
                <ProtectedRoute>
                  <PIDHomeScreen />
                </ProtectedRoute>
              }
            />
            <Route
              path="/pid-studio/ingest"
              element={
                <ProtectedRoute>
                  <PIDIngestPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/pid-studio/review"
              element={
                <ProtectedRoute>
                  <PIDReviewPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/pid-studio/canvas"
              element={
                <ProtectedRoute>
                  <PIDCanvasPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/pid-studio/describe"
              element={
                <ProtectedRoute>
                  <PIDDescribePage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/pid-studio/validation"
              element={
                <ProtectedRoute>
                  <PIDValidationPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/pid-studio/export"
              element={
                <ProtectedRoute>
                  <PIDExportPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/solution/search"
              element={
                <ProtectedRoute>
                  <Project />
                </ProtectedRoute>
              }
            />


            <Route
              path="/solution/search/admin"
              element={
                <ProtectedRoute requireAdmin>
                  <AdminDashboard />
                </ProtectedRoute>
              }
            />

            <Route
              path="/solution/admin"
              element={
                <ProtectedRoute requireAdmin>
                  <AdminDashboard />
                </ProtectedRoute>
              }
            />

            {/* Search routes */}
            <Route
              path="/search"
              element={
                <ProtectedRoute>
                  <Index />
                </ProtectedRoute>
              }
            />

            <Route
              path="/search/admin"
              element={
                <ProtectedRoute requireAdmin>
                  <AdminDashboard />
                </ProtectedRoute>
              }
            />

            {/* Configure routes */}
            <Route
              path="/configure"
              element={
                <ProtectedRoute>
                  <AssetConfiguration />
                </ProtectedRoute>
              }
            />

            <Route
              path="/configure/admin"
              element={
                <ProtectedRoute requireAdmin>
                  <AdminDashboard />
                </ProtectedRoute>
              }
            />

            {/* Procurement routes removed */}

            {/* Catalog routes */}
            <Route
              path="/catalog"
              element={
                <ProtectedRoute>
                  <Catalog />
                </ProtectedRoute>
              }
            />

            {/* Assets routes */}
            <Route
              path="/assets"
              element={
                <ProtectedRoute>
                  <Assets />
                </ProtectedRoute>
              }
            />

            {/* Legacy routes */}
            <Route
              path="/admin"
              element={
                <ProtectedRoute requireAdmin>
                  <AdminDashboard />
                </ProtectedRoute>
              }
            />

            <Route
              path="/usage"
              element={
                <ProtectedRoute>
                  <UtilizationPage />
                </ProtectedRoute>
              }
            />

            <Route
              path="/credits"
              element={
                <ProtectedRoute>
                  <CreditsPage />
                </ProtectedRoute>
              }
            />

            <Route
              path="/benchmarks"
              element={
                <ProtectedRoute requireAdmin>
                  <Benchmarks />
                </ProtectedRoute>
              }
            />


            {/* 404 */}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </AuthProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
};

export default App;
