import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { checkAuth, login as apiLogin, logout as apiLogout, signup as apiSignup, microsoftSignIn as apiMicrosoftSignIn, microsoftSignUp as apiMicrosoftSignUp } from '../components/AIRecommender/api';
import { UserCredentials } from '../components/AIRecommender/types';
import { useToast } from '../hooks/use-toast';

// UPDATED User interface to include role and status
interface User {
  username: string;
  name: string;
  firstName?: string;
  lastName?: string;
  email: string;
  role: "admin" | "user";        // change to union type for safety
  status: "pending" | "active" | "rejected";  // 'pending', 'active', or 'rejected'
  company?: string;
  location?: string;
}

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: User | null;
  isAdmin: boolean;
  userSessionId: string | null;  // NEW: Unified session ID for entire login session
  refreshUser: () => Promise<void>;
  login: (credentials: Omit<UserCredentials, 'email'>) => Promise<void>;
  signup: (credentials: UserCredentials) => Promise<void>;
  microsoftLogin: (accessToken: string, email: string, name?: string) => Promise<void>;
  microsoftSignup: (accessToken: string, email: string, name?: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// Storage key for user session ID (persists across page refreshes)
const USER_SESSION_ID_KEY = 'user_session_id';
// Storage key for auth token (JWT for cross-origin requests)
const AUTH_TOKEN_KEY = 'auth_token';

// Helper function to generate a new user session ID
const generateUserSessionId = (): string => {
  return `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
};

// Helper function to attach auth token to fetches
const authFetch = (url: string, init?: RequestInit) => {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  return fetch(url, {
    ...init,
    headers: {
      ...init?.headers,
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    }
  });
};


interface AuthProviderProps {
  children: ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [user, setUser] = useState<User | null>(null);
  // NEW: User session ID - same across all screens for entire login session
  const [userSessionId, setUserSessionId] = useState<string | null>(() => {
    // Try to restore from localStorage on mount
    return localStorage.getItem(USER_SESSION_ID_KEY);
  });
  const { toast } = useToast();

  const checkAuthStatus = async () => {
    try {
      const authData = await checkAuth();
      setIsAuthenticated(!!authData);
      if (authData) {
        // Type cast to the new User interface
        setUser(authData.user as User);

        // Ensure user session ID exists if authenticated
        if (!localStorage.getItem(USER_SESSION_ID_KEY)) {
          const newSessionId = generateUserSessionId();
          localStorage.setItem(USER_SESSION_ID_KEY, newSessionId);
          setUserSessionId(newSessionId);
          console.log('[AUTH] Generated new user session ID on auth check:', newSessionId);
        }


      } else {
        // Not authenticated - clear session ID
        localStorage.removeItem(USER_SESSION_ID_KEY);
        setUserSessionId(null);
      }
    } catch (error) {
      setIsAuthenticated(false);
      setUser(null);
      localStorage.removeItem(USER_SESSION_ID_KEY);
      setUserSessionId(null);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    checkAuthStatus();
  }, []);

  const refreshUser = async () => {
    await checkAuthStatus();
  };

  const login = async (credentials: Omit<UserCredentials, 'email'>) => {
    try {
      setIsLoading(true);
      const response = await apiLogin(credentials);

      // CLEAR ALL OLD STATE to ensure fresh project on every login
      // Clear localStorage (keeps login-related data from response)
      localStorage.clear();

      // Clear sessionStorage
      sessionStorage.clear();

      // Clear IndexedDB project state
      try {
        const DBDeleteRequest = window.indexedDB.deleteDatabase("project_page_db");
        DBDeleteRequest.onerror = () => {
          console.error("Error deleting database on login.");
        };
        DBDeleteRequest.onsuccess = () => {
          console.log("Project database deleted for fresh start on login");
        };
      } catch (e) {
        console.error("Failed to delete IndexedDB on login", e);
      }

      // NEW: Generate and store user session ID for the entire login session
      const newUserSessionId = generateUserSessionId();
      localStorage.setItem(USER_SESSION_ID_KEY, newUserSessionId);
      setUserSessionId(newUserSessionId);
      console.log('[AUTH] Generated new user session ID on login:', newUserSessionId);

      // Store JWT auth token for cross-origin requests (bypasses third-party cookie blocking)
      if (response.token) {
        localStorage.setItem(AUTH_TOKEN_KEY, response.token);
        console.log('[AUTH] Stored auth token for API authentication');
      }



      setIsAuthenticated(true);
      // Set the user with the new role and status
      setUser(response.user as User);

      toast({
        title: "Success",
        description: "Successfully logged in!",
      });
    } catch (error: any) {
      const status = error.response?.status;
      const errorMessage = error.response?.data?.error || error.message || "Invalid credentials";
      let description = errorMessage;
      if (status === 404) {
        description = "No account found with that username. Please register.";
      } else if (status === 401) {
        description = "Incorrect password.";
      } else if (status === 403) {
        if (errorMessage.toLowerCase().includes("pending")) {
          description = "Your account is pending admin approval.";
        } else if (errorMessage.toLowerCase().includes("rejected")) {
          description = "Your account has been rejected. Please contact support.";
        }
      }
      toast({
        title: "Login Failed",
        description,
        variant: "destructive",
      });
      throw error;
    } finally {
      setIsLoading(false);
    }
  };

  const signup = async (credentials: UserCredentials) => {
    try {
      setIsLoading(true);
      const response = await apiSignup(credentials);
      // The signup message now indicates admin approval is needed
      toast({
        title: "Success",
        description: response.message || "Account created successfully! Awaiting admin approval.",
      });
    } catch (error: any) {
      toast({
        title: "Signup Failed",
        description: error.message || "Failed to create account",
        variant: "destructive",
      });
      throw error;
    } finally {
      setIsLoading(false);
    }
  };

  const microsoftSignup = async (accessToken: string, email: string, name?: string) => {
    try {
      setIsLoading(true);
      const response = await apiMicrosoftSignUp(accessToken, email, name);

      if (!response.success) {
        throw new Error(response.error || 'Microsoft Sign-Up failed');
      }

      // Account created successfully, show pending approval message
      toast({
        title: "Success",
        description: response.message || "Account created with Microsoft! Awaiting admin approval.",
      });
    } catch (error: any) {
      const errorMessage = error.message || "Microsoft Sign-Up failed";
      toast({
        title: "Microsoft Sign-Up Failed",
        description: errorMessage,
        variant: "destructive",
      });
      throw error;
    } finally {
      setIsLoading(false);
    }
  };

  const microsoftLogin = async (accessToken: string, email: string, name?: string) => {
    try {
      setIsLoading(true);
      const response = await apiMicrosoftSignIn(accessToken, email, name);

      if (!response.success) {
        throw new Error(response.error || 'Microsoft Sign-In failed');
      }

      // CLEAR ALL OLD STATE to ensure fresh session
      localStorage.clear();
      sessionStorage.clear();

      // Clear IndexedDB project state
      try {
        const DBDeleteRequest = window.indexedDB.deleteDatabase("project_page_db");
        DBDeleteRequest.onerror = () => {
          console.error("Error deleting database on Microsoft login.");
        };
        DBDeleteRequest.onsuccess = () => {
          console.log("Project database deleted for fresh start on Microsoft login");
        };
      } catch (e) {
        console.error("Failed to delete IndexedDB on Microsoft login", e);
      }

      // Generate and store user session ID
      const newUserSessionId = generateUserSessionId();
      localStorage.setItem(USER_SESSION_ID_KEY, newUserSessionId);
      setUserSessionId(newUserSessionId);
      console.log('[AUTH] Generated new user session ID on Microsoft login:', newUserSessionId);



      setIsAuthenticated(true);
      setUser(response.user as User);

      const isNew = response.isNewUser;
      toast({
        title: "Success",
        description: isNew
          ? "Account created and logged in with Microsoft!"
          : "Successfully signed in with Microsoft!",
      });
    } catch (error: any) {
      const errorMessage = error.message || "Microsoft Sign-In failed";
      toast({
        title: "Microsoft Sign-In Failed",
        description: errorMessage,
        variant: "destructive",
      });
      throw error;
    } finally {
      setIsLoading(false);
    }
  };

  const logout = async () => {
    try {
      setIsLoading(true);
      await apiLogout();

      // Clear all local state validation
      setIsAuthenticated(false);
      setUser(null);

      // NEW: Clear user session ID on logout
      localStorage.removeItem(USER_SESSION_ID_KEY);
      setUserSessionId(null);
      console.log('[AUTH] Cleared user session ID on logout');

      // CLEAR ALL LOCAL STORAGE to ensure fresh session on next login
      localStorage.clear();

      // CLEAR ALL SESSION STORAGE (including lastSourcePage, etc.)
      sessionStorage.clear();

      // Clear IndexedDB project state
      try {
        const DBDeleteRequest = window.indexedDB.deleteDatabase("project_page_db");
        DBDeleteRequest.onerror = (event) => {
          console.error("Error deleting database on logout.");
        };
        DBDeleteRequest.onsuccess = (event) => {
          console.log("Project database deleted successfully on logout");
        };
      } catch (e) {
        console.error("Failed to delete IndexedDB", e);
      }

      toast({
        title: "Success",
        description: "Successfully logged out!",
      });
    } catch (error: any) {
      toast({
        title: "Logout Failed",
        description: error.message || "Failed to logout",
        variant: "destructive",
      });
    } finally {
      setIsLoading(false);
    }
  };

  const value = {
    isAuthenticated,
    isLoading,
    user,
    isAdmin: user?.role === "admin",   // added helper
    userSessionId,  // NEW: Expose user session ID to all components
    refreshUser,
    login,
    signup,
    microsoftLogin,
    microsoftSignup,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
