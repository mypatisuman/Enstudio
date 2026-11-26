import { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Eye, EyeOff, Brain, ArrowLeft, Loader2 } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { msalInstance } from '../lib/msal';

// DEBUG: Log MSAL configuration
console.log('[MSAL CONFIG]', {
  redirectUri: window.location.origin,
  currentOrigin: window.location.origin
});

const Login = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showValidation, setShowValidation] = useState(false);
  const [microsoftLoading, setMicrosoftLoading] = useState(false);
  const [isLoginLoading, setIsLoginLoading] = useState(false);
  const { login, microsoftLogin, isLoading, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  // Redirect automatically if already logged in
  useEffect(() => {
    if (isAuthenticated) {
      navigate('/chat', { replace: true });
    }
  }, [isAuthenticated, navigate]);

  // Handle MSAL redirect response (if user is coming back from Microsoft redirect)
  useEffect(() => {
    let hasRun = false; // Prevent multiple runs

    const handleRedirect = async () => {
      if (hasRun) return;
      hasRun = true;

      try {
        const response = await msalInstance.handleRedirectPromise();
        if (response?.account?.username) {
          console.log('[MSAL] ✅ Redirect login successful:', response.account.username);
          setMicrosoftLoading(true);
          await microsoftLogin(
            response.accessToken,
            response.account.username,
            response.account.name || undefined
          );
          sessionStorage.setItem('from_login', 'true');
          navigate('/chat');
        }
      } catch (error: any) {
        // Ignore expected cache error (happens when there's no redirect to handle)
        if (error?.errorCode !== 'no_token_request_cache_error') {
          console.error('[MSAL] Redirect handling error:', error);
        }
      } finally {
        setMicrosoftLoading(false);
      }
    };
    handleRedirect();
  }, []); // Empty deps - run once on mount

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setShowValidation(true);

    if (!username.trim() || !password.trim()) return;

    setIsLoginLoading(true);
    try {
      await login({ username: username.trim(), password });
      sessionStorage.setItem('from_login', 'true');
      navigate('/chat');
    } catch (error) {
      // handled in AuthContext
    } finally {
      setIsLoginLoading(false);
    }
  };

  // Form validation
  const isFormValid = !!(username.trim() && password.trim());

  const handleMicrosoftSignIn = async () => {
    // Prevent multiple sign-in attempts
    if (microsoftLoading) {
      console.warn('[MSAL] Sign-in already in progress, ignoring click');
      return;
    }

    setMicrosoftLoading(true);
    console.log('[MSAL] Starting Microsoft sign-in flow...');

    try {
      // Check if there's already an interaction in progress
      const accounts = msalInstance.getAllAccounts();
      if (accounts.length > 0) {
        console.log('[MSAL] Account already exists, attempting silent login');
        // Try silent login first
        try {
          const silentResult = await msalInstance.acquireTokenSilent({
            scopes: ['User.Read'],
            account: accounts[0],
          });

          if (silentResult?.account?.username) {
            console.log('[MSAL] ✅ Silent login successful');
            await microsoftLogin(
              silentResult.accessToken,
              silentResult.account.username,
              silentResult.account.name || undefined
            );
            sessionStorage.setItem('from_login', 'true');
            navigate('/chat');
            return;
          }
        } catch (silentError) {
          console.log('[MSAL] Silent login failed, falling back to popup');
        }
      }

      console.log('[MSAL] Using redirect flow for authentication...');

      // Use redirect flow (more reliable than popup)
      await msalInstance.loginRedirect({
        scopes: ['User.Read'],
        prompt: 'select_account'
      });
      // Page will redirect to Microsoft, then come back
      // The useEffect above will handle the response
    } catch (error: any) {
      // Handle specific MSAL errors
      if (error?.errorCode === 'interaction_in_progress') {
        console.warn('[MSAL] ⚠️ Interaction already in progress - user clicked too quickly');
        // Silently ignore - user will see the existing popup
      } else if (error?.errorCode === 'user_cancelled') {
        console.log('[MSAL] ℹ️ User cancelled the sign-in');
      } else {
        console.error('[MSAL] ❌ Sign-In error:', error);
        console.error('[MSAL] Error details:', {
          errorCode: error?.errorCode,
          errorMessage: error?.errorMessage,
          subError: error?.subError
        });
      }
    } finally {
      setMicrosoftLoading(false);
    }
  };

  return (
    <>
      <div className="h-screen app-glass-gradient flex items-center justify-center px-6 overflow-y-auto custom-visible-scrollbar-dark">
        {/* Decorative background images */}
        <div className="fixed inset-0 pointer-events-none overflow-hidden z-[0] flex items-center justify-center">
            <img src="/engenie logo.jpeg" alt="" className="w-80 h-80 md:w-[32rem] md:h-[32rem] object-contain opacity-[0.04] select-none translate-y-8 md:translate-y-12" />
        </div>
        <div className="w-full max-w-md transition-all duration-300 hover:scale-[1.02]">
          <div className="acrylic-glass-pill backdrop-blur-3xl p-8 relative transition-all duration-300 hover:shadow-2xl">
            {/* Back Button - Top Left */}
            <button
              onClick={() => navigate('/')}
              className="absolute top-10 left-8 text-muted-foreground hover:text-foreground transition-colors p-2 -ml-2 -mt-2 z-50"
              title="Back to Home"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            {/* Header */}
            <div className="text-center space-y-4 animate-item stagger-1">
              <div className="w-16 h-16 mx-auto rounded-full overflow-hidden shadow bg-white">
                <img src="/engenie logo.jpeg" alt="Logo" className="w-full h-full object-cover" />
              </div>
              <div>
                <h1 className="text-3xl font-bold">
                  Welcome Back
                </h1>
                <p className="text-muted-foreground mt-2 text-base">
                  Sign in to access your account
                </p>
              </div>
            </div>

            {/* Form */}
            <div>
              <form onSubmit={handleSubmit} noValidate className="space-y-6">
                {/* Username */}
                <div className="space-y-2 animate-item stagger-2">
                  <Label htmlFor="username" className="font-medium">
                    Username
                  </Label>
                  <div className="relative">
                    <Input
                      id="username"
                      type="text"
                      placeholder="Enter your username"
                      value={username}
                      onChange={(e) => {
                        setUsername(e.target.value);
                        e.target.setCustomValidity('');
                      }}
                      onInvalid={(e) => {
                        (e.target as HTMLInputElement).setCustomValidity('Enter username');
                      }}
                      className={`form-glass-input rounded-xl ${showValidation && !username.trim() ? 'border-red-500 focus:ring-red-500' : ''}`}
                      required
                    />
                  </div>
                  {showValidation && !username.trim() && (
                    <p className="text-xs text-red-500 mt-1 animate-in fade-in duration-200">Username is required</p>
                  )}
                </div>

                {/* Password */}
                <div className="space-y-2 animate-item stagger-3">
                  <Label htmlFor="password" className="font-medium">
                    Password
                  </Label>
                  <div className="relative hover:scale-[1.02] transition-all duration-300">
                    <Input
                      id="password"
                      type={showPassword ? 'text' : 'password'}
                      placeholder="Enter your password"
                      value={password}
                      onChange={(e) => {
                        setPassword(e.target.value);
                        e.target.setCustomValidity('');
                      }}
                      onInvalid={(e) => {
                        (e.target as HTMLInputElement).setCustomValidity('Enter password');
                      }}
                      className={`form-glass-input pr-12 rounded-xl hover:scale-100 ${showValidation && !password.trim() ? 'border-red-500 focus:ring-red-500' : ''}`}
                      required
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-foreground transition-colors hover:bg-transparent transition-transform hover:scale-110 active:scale-95"
                      onClick={() => setShowPassword(!showPassword)}
                    >
                      {showPassword ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </Button>
                  </div>
                  {showValidation && !password.trim() && (
                    <p className="text-xs text-red-500 mt-1 animate-in fade-in duration-200">Password is required</p>
                  )}
                </div>

                {/* Submit Button */}
                <button
                  type="submit"
                  disabled={isLoginLoading || isLoading || !isFormValid}
                  className={`w-full font-semibold rounded-xl px-4 py-3 animate-item stagger-4 transition-opacity duration-300 hover:brightness-100 hover:saturate-100 ${isLoginLoading || isLoading || !isFormValid
                    ? 'btn-glass-primary opacity-50'
                    : 'btn-glass-primary'
                    }`}
                >
                  {isLoginLoading ? (
                    <div className="flex items-center justify-center gap-2">
                      <Loader2 className="h-5 w-5 animate-spin" />
                      <span>Signing in...</span>
                    </div>
                  ) : (
                    'Sign In'
                  )}
                </button>

                {/* Divider - COMMENTED OUT FOR NOW */}
                {/* <div className="flex items-center gap-3 -my-1 animate-item stagger-5">
                <div className="flex-1 h-px bg-border/50" />
                <span className="text-xs text-muted-foreground font-medium">or</span>
                <div className="flex-1 h-px bg-border/50" />
              </div> */}

                {/* Microsoft Sign-In Button - COMMENTED OUT FOR NOW */}
                {/* <div className="animate-item stagger-6">
                <Button
                  type="button"
                  onClick={handleMicrosoftSignIn}
                  disabled={microsoftLoading || isLoading}
                  className="w-full rounded-xl px-4 py-3 h-auto font-semibold transition-all duration-300 hover:scale-[1.02] active:scale-[0.98] text-foreground hover:brightness-105"
                  style={{ background: 'rgba(255,255,255,0.5)', backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)', border: '1px solid rgba(255,255,255,0.5)' }}
                >
                  {microsoftLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  ) : (
                    <svg className="h-5 w-5 mr-2" viewBox="0 0 21 21" xmlns="http://www.w3.org/2000/svg">
                      <rect x="1" y="1" width="9" height="9" fill="#F25022" />
                      <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
                      <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
                      <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
                    </svg>
                  )}
                  {microsoftLoading ? 'Signing in...' : 'Sign in with Microsoft'}
                </Button>
              </div> */}

                {/* Signup link */}
                <div className="text-center pt-4 animate-item stagger-7">
                  <p className="text-muted-foreground text-sm">
                    Don't have an account?{' '}
                    <Link
                      to="/signup"
                      className="font-semibold group relative inline-block"
                    >
                      <span className="relative z-10 text-secondary group-hover:text-primary transition-colors duration-200">
                        Sign up
                      </span>
                      <span className="absolute bottom-0 left-0 w-0 h-0.5 bg-primary group-hover:w-full transition-all duration-300 ease-out"></span>
                    </Link>
                  </p>
                </div>
              </form>
            </div>
          </div>
        </div>
      </div>
    </>
  );
};

export default Login;
