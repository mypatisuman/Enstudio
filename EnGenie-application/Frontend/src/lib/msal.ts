import { PublicClientApplication } from '@azure/msal-browser';

const msalConfig = {
  auth: {
    clientId: import.meta.env.VITE_AZURE_CLIENT_ID || '',
    authority: `https://login.microsoftonline.com/${import.meta.env.VITE_AZURE_TENANT_ID || 'common'}`,
    redirectUri: window.location.origin, // Use main app for redirect flow
  },
  cache: {
    cacheLocation: 'sessionStorage' as const,
    storeAuthStateInCookie: false,
  },
  system: {
    allowRedirectInIframe: false, // Prevent iframe redirects
    loggerOptions: {
      logLevel: import.meta.env.DEV ? 3 : 0, // Verbose in dev, none in prod
    }
  }
};

export const msalInstance = new PublicClientApplication(msalConfig);
