import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { msalInstance } from "./lib/msal";
import "./index.css";

msalInstance.initialize()
    .then(() => {
        return msalInstance.handleRedirectPromise();
    })
    .then(() => {
        // Redirect handled or no redirect to handle
    })
    .catch((error) => {
        // Handle both initialize and redirect errors here
        if (error?.errorCode !== 'no_token_request_cache_error') {
            console.error('[MSAL Main] MSAL error:', error);
        }
    })
    .finally(() => {
        // Always render the app, even if MSAL initialization fails
        createRoot(document.getElementById("root")!).render(
            <ErrorBoundary>
                <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
                    <App />
                </BrowserRouter>
            </ErrorBoundary>
        );
    });

