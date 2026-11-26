import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Eye, EyeOff, ArrowLeft, Upload, Loader2, CheckCircle2, Mail } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { validateEmail, sendOtp, verifyOtp } from '../components/AIRecommender/api';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { msalInstance } from '../lib/msal';

const Signup = () => {
  const [step, setStep] = useState(1);

  // Step 1 Fields
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');

  // Step 2 Fields
  const [company, setCompany] = useState('');
  const [location, setLocation] = useState('');

  // Step 3 Fields - Documents
  const [strategy, setStrategy] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [standardsFile, setStandardsFile] = useState<File | null>(null);
  const [assetsFile, setAssetsFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const standardsFileInputRef = useRef<HTMLInputElement>(null);
  const assetsFileInputRef = useRef<HTMLInputElement>(null);

  // Step 4 Fields - Security
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  // Email validation
  const [emailError, setEmailError] = useState('');
  const [emailValidating, setEmailValidating] = useState(false);
  const [emailValid, setEmailValid] = useState(false);
  const emailValidationTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // OTP Verification
  const [isEmailVerified, setIsEmailVerified] = useState(false);
  const [isOtpModalOpen, setIsOtpModalOpen] = useState(false);
  const [otpCode, setOtpCode] = useState('');
  const [otpSending, setOtpSending] = useState(false);
  const [otpVerifying, setOtpVerifying] = useState(false);
  const [otpError, setOtpError] = useState('');
  const [otpSuccess, setOtpSuccess] = useState('');
  const [resendTimer, setResendTimer] = useState(0);
  const resendTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Validation tracking
  const [showValidation, setShowValidation] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // Status
  const [isPending, setIsPending] = useState(false);
  const [microsoftLoading, setMicrosoftLoading] = useState(false);
  const { signup, microsoftLogin, microsoftSignup, isLoading, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  // NOTE: Signup page should NOT auto-redirect authenticated users
  // Users should always be able to access the signup form to create new accounts

  // Handle MSAL redirect response (if user is coming back from Microsoft redirect)
  useEffect(() => {
    let hasRun = false; // Prevent multiple runs

    const handleRedirect = async () => {
      if (hasRun) return;
      hasRun = true;

      try {
        const response = await msalInstance.handleRedirectPromise();
        if (response?.account?.username) {
          console.log('[MSAL Signup] ✅ Redirect signup successful:', response.account.username);
          setMicrosoftLoading(true);
          await microsoftSignup(
            response.accessToken,
            response.account.username,
            response.account.name || undefined
          );
          // Show pending approval screen
          setIsPending(true);
        }
      } catch (error: any) {
        // Ignore expected cache error (happens when there's no redirect to handle)
        if (error?.errorCode !== 'no_token_request_cache_error') {
          console.error('[MSAL Signup] Redirect handling error:', error);
        }
      } finally {
        setMicrosoftLoading(false);
      }
    };
    handleRedirect();
  }, []); // Empty deps - run once on mount

  // Full validation chain triggered while typing (debounced)
  const checkEmail = useCallback(async (emailValue: string) => {
    if (!emailValue || !emailValue.includes('@')) {
      setEmailError('');
      setEmailValid(false);
      return;
    }

    // Step 1: Basic format check
    const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
    if (!emailRegex.test(emailValue)) {
      setEmailError('Please enter a valid email format');
      setEmailValid(false);
      return;
    }

    // New Step: Restrict personal email domains
    if (/@(gmail|yahoo|hotmail|outlook|live)\./i.test(emailValue)) {
      setEmailError('Please enter your organization email address');
      setEmailValid(false);
      return;
    }

    // Step 2-5: MX + domain + duplicate + Azure AD via API
    setEmailValidating(true);
    setEmailError('');
    setEmailValid(false);

    try {
      const result = await validateEmail(emailValue);
      if (!result.valid) {
        setEmailError(result.error || 'Please enter a valid email address');
        setEmailValid(false);
      } else {
        setEmailError('');
        setEmailValid(true);
      }
    } catch {
      setEmailValid(true); // Don't block if validation service unavailable
    } finally {
      setEmailValidating(false);
    }
  }, []);

  const handleEmailChange = (value: string) => {
    setEmail(value);
    setEmailError('');
    setEmailValid(false);
    setIsEmailVerified(false);
    if (fieldErrors.email) setFieldErrors(prev => ({ ...prev, email: '' }));

    if (emailValidationTimer.current) {
      clearTimeout(emailValidationTimer.current);
    }

    // Debounce: run full validation 800ms after user stops typing
    if (value && value.includes('@') && value.includes('.')) {
      emailValidationTimer.current = setTimeout(() => {
        checkEmail(value);
      }, 800);
    }
  };

  const handleSendOtp = async () => {
    if (!emailValid || emailValidating || resendTimer > 0) return;

    setOtpSending(true);
    setOtpError('');
    setOtpSuccess('');

    try {
      // All validations already passed — just send OTP
      const result = await sendOtp(email);
      if (result.success) {
        setOtpSuccess('Verification code sent! Check your email.');
        setIsOtpModalOpen(true);
        setOtpCode('');

        setResendTimer(60);
        if (resendTimerRef.current) clearInterval(resendTimerRef.current);
        resendTimerRef.current = setInterval(() => {
          setResendTimer((prev) => {
            if (prev <= 1) {
              if (resendTimerRef.current) clearInterval(resendTimerRef.current);
              return 0;
            }
            return prev - 1;
          });
        }, 1000);
      } else {
        setOtpError(result.error || 'Failed to send verification code');
      }
    } catch (error) {
      setOtpError('Failed to send verification code. Please try again.');
    } finally {
      setOtpSending(false);
    }
  };

  const handleVerifyOtp = async () => {
    if (!otpCode || otpCode.length !== 6) {
      setOtpError('Please enter a valid 6-digit code');
      return;
    }

    setOtpVerifying(true);
    setOtpError('');

    try {
      const result = await verifyOtp(email, otpCode);
      if (result.verified) {
        setIsEmailVerified(true);
        setOtpSuccess('Email verified successfully!');
        setTimeout(() => {
          setIsOtpModalOpen(false);
          setOtpCode('');
        }, 1500);
      } else {
        setOtpError(result.error || 'Invalid verification code');
      }
    } catch (error) {
      setOtpError('Verification failed. Please try again.');
    } finally {
      setOtpVerifying(false);
    }
  };

  const handleCloseOtpModal = () => {
    setIsOtpModalOpen(false);
    setOtpCode('');
    setOtpError('');
    setOtpSuccess('');
    if (resendTimerRef.current) clearInterval(resendTimerRef.current);
    setResendTimer(0);
  };

  const handleEditEmail = () => {
    setIsOtpModalOpen(false);
    setOtpCode('');
    setOtpError('');
    setOtpSuccess('');
    setIsEmailVerified(false);
    setEmailValid(false);
    if (resendTimerRef.current) clearInterval(resendTimerRef.current);
    setResendTimer(0);
  };

  const handleMicrosoftSignIn = async () => {
    // Prevent multiple sign-up attempts
    if (microsoftLoading) {
      console.warn('[MSAL Signup] Sign-up already in progress, ignoring click');
      return;
    }

    setMicrosoftLoading(true);
    console.log('[MSAL Signup] Starting Microsoft sign-up flow...');

    try {
      // Check if there's already an interaction in progress
      const accounts = msalInstance.getAllAccounts();
      if (accounts.length > 0) {
        console.log('[MSAL Signup] Account already exists, attempting silent signup');
        // Try silent token acquisition first
        try {
          const silentResult = await msalInstance.acquireTokenSilent({
            scopes: ['User.Read'],
            account: accounts[0],
          });

          if (silentResult?.account?.username) {
            console.log('[MSAL Signup] ✅ Silent token acquired');
            await microsoftSignup(
              silentResult.accessToken,
              silentResult.account.username,
              silentResult.account.name || undefined
            );
            setIsPending(true);
            return;
          }
        } catch (silentError) {
          console.log('[MSAL Signup] Silent token failed, falling back to redirect');
        }
      }

      console.log('[MSAL Signup] Using redirect flow for authentication...');

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
        console.warn('[MSAL Signup] ⚠️ Interaction already in progress - user clicked too quickly');
        // Silently ignore - user will see the existing flow
      } else if (error?.errorCode === 'user_cancelled') {
        console.log('[MSAL Signup] ℹ️ User cancelled the sign-up');
      } else {
        console.error('[MSAL Signup] ❌ Sign-Up error:', error);
        console.error('[MSAL Signup] Error details:', {
          errorCode: error?.errorCode,
          errorMessage: error?.errorMessage,
          subError: error?.subError
        });
        setOtpError(error?.errorMessage || 'Microsoft Sign-Up failed. Please try again.');
      }
    } finally {
      setMicrosoftLoading(false);
    }
  };

  const handleNext = () => {
    setShowValidation(true);
    // Basic validation per step
    if (step === 1) {
      if (isStep1Valid) {
        setStep(2);
        setShowValidation(false);
      }
    } else if (step === 2) {
      if (isStep2Valid) {
        setStep(3);
        setShowValidation(false);
      }
    } else if (step === 3) {
      if (isStep3Valid) {
        setStep(4);
        setShowValidation(false);
      }
    }
  };

  const handlePrev = () => {
    setStep(step - 1);
    setShowValidation(false);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
    }
  };

  const handleStandardsFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setStandardsFile(e.target.files[0]);
    }
  };

  const handleAssetsFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setAssetsFile(e.target.files[0]);
    }
  };

  const removeFile = () => {
    setFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const removeStandardsFile = () => {
    setStandardsFile(null);
    if (standardsFileInputRef.current) {
      standardsFileInputRef.current.value = '';
    }
  };

  const removeAssetsFile = () => {
    setAssetsFile(null);
    if (assetsFileInputRef.current) {
      assetsFileInputRef.current.value = '';
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setShowValidation(true);

    const errors: Record<string, string> = {};

    if (!firstName.trim()) errors.firstName = 'First name is required';
    if (!lastName.trim()) errors.lastName = 'Last name is required';
    if (!email.trim()) errors.email = 'Email is required';
    else if (emailError) errors.email = emailError;
    else if (!isEmailVerified) errors.email = 'Please verify your email with OTP';

    // Company and Location are optional, no required errors here

    if (!username.trim()) errors.username = 'Username is required';
    if (!password) errors.password = 'Password is required';
    else if (!/^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$/.test(password))
      errors.password = 'Min 8 chars with uppercase, lowercase, number & special character (@$!%*?&)';
    if (!confirmPassword) errors.confirmPassword = 'Please confirm your password';
    else if (password !== confirmPassword) errors.confirmPassword = 'Passwords do not match';

    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      if (errors.firstName || errors.lastName || errors.email) setStep(1);
      else if (errors.username || errors.password || errors.confirmPassword) setStep(4);
      return;
    }

    setFieldErrors({});

    try {
      // Create FormData to handle file upload
      const formData = new FormData();
      formData.append('first_name', firstName.trim());
      formData.append('last_name', lastName.trim());
      formData.append('email', email.trim());
      formData.append('username', username.trim());
      formData.append('password', password);

      // Optional fields
      if (company) formData.append('company', company.trim());
      if (location) formData.append('location', location.trim());
      if (strategy) formData.append('strategy', strategy.trim());

      if (file) {
        formData.append('document', file);
      }

      if (standardsFile) {
        formData.append('standards_document', standardsFile);
      }

      if (assetsFile) {
        formData.append('assets_document', assetsFile);
      }

      // Cast to any since AuthContext expects UserCredentials object but we are sending FormData
      // Backend is updated to handle FormData
      await signup(formData as any);

      setIsPending(true);
    } catch (error) {
      console.error("Signup failed:", error);
      setIsPending(false);
    }
  };

  // Step Validations
  const isStep1Valid = !!(firstName.trim() && lastName.trim() && email.trim() && !emailError && !emailValidating && isEmailVerified);
  const isStep2Valid = true; // Optional (company, location)
  const isStep3Valid = true; // Optional (documents)
  const isStep4Valid = !!(
    username.trim() &&
    /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$/.test(password) &&
    confirmPassword &&
    (password === confirmPassword)
  );
  const isFormValid = isStep1Valid && isStep2Valid && isStep4Valid;

  if (isPending) {
    return (
      <div className="h-screen overflow-y-auto custom-no-scrollbar app-glass-gradient flex items-center justify-center p-6">
        {/* Decorative background images */}
        <div className="fixed inset-0 pointer-events-none overflow-hidden z-[0] flex items-center justify-center">
            <img src="/engenie logo.jpeg" alt="" className="w-80 h-80 md:w-[32rem] md:h-[32rem] object-contain opacity-[0.04] select-none translate-y-8 md:translate-y-12" />
        </div>
        <div className="w-full max-w-md">
          <div className="acrylic-glass-pill backdrop-blur-3xl p-8 text-center relative">
            <div className="w-16 h-16 mx-auto mb-6 rounded-full overflow-hidden shadow bg-white">
              <img src="/engenie logo.jpeg" alt="Logo" className="w-full h-full object-cover" />
            </div>
            <h2 className="text-2xl font-bold mb-4">Account Created!</h2>
            <p className="text-muted-foreground mb-6">
              Your account has been created and is awaiting admin approval. You will receive an email once your account is active.
            </p>
            <button onClick={() => navigate('/login')} className="btn-glass-primary w-full px-4 py-3 rounded-lg">Go to Login</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen app-glass-gradient overflow-hidden">
      {/* Decorative background images */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-[0] flex items-center justify-center">
          <img src="/engenie logo.jpeg" alt="" className="w-80 h-80 md:w-[32rem] md:h-[32rem] object-contain opacity-[0.04] select-none translate-y-8 md:translate-y-12" />
      </div>
      <div className="h-full overflow-y-auto custom-visible-scrollbar-dark flex items-start justify-center py-8 px-6">
      <div className="w-full max-w-md transition-all duration-300 hover:scale-[1.02]">
        <div className="acrylic-glass-pill backdrop-blur-3xl p-8 relative transition-all duration-300 hover:shadow-2xl min-h-[600px] flex flex-col">
          {/* Back Button */}
          <button
            onClick={() => navigate('/')}
            className="absolute top-10 left-8 text-muted-foreground hover:text-foreground transition-colors p-2 -ml-2 -mt-2 z-50"
            title="Back to Home"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>

          {/* Header */}
          <div className="text-center space-y-4 mb-8 animate-item stagger-1">
            <div className="w-16 h-16 mx-auto rounded-full overflow-hidden shadow bg-white">
              <img src="/engenie logo.jpeg" alt="Logo" className="w-full h-full object-cover" />
            </div>
            <div>
              <h1 className="text-3xl font-bold">Create Account</h1>
              <p className="text-muted-foreground mt-2 text-base">Step {step} of 4</p>
            </div>
          </div>

          <form onSubmit={handleSubmit} noValidate className="flex-1 flex flex-col justify-between space-y-6">

            {/* STEP 1: Personal Info */}
            {step === 1 && (
              <div className="space-y-4">
                <div className="space-y-2 animate-item stagger-2">
                  <Label htmlFor="firstName">First Name</Label>
                  <div className="relative">
                    <Input
                      id="firstName"
                      value={firstName}
                      onChange={(e) => {
                        setFirstName(e.target.value);
                        e.target.setCustomValidity('');
                      }}
                      onInvalid={(e) => {
                        (e.target as HTMLInputElement).setCustomValidity('Enter first name');
                      }}
                      className={`form-glass-input rounded-xl ${showValidation && !firstName.trim() ? 'border-red-500 focus:ring-red-500' : ''}`}
                      placeholder="John"
                      required
                    />
                  </div>
                  {showValidation && !firstName.trim() && (
                    <p className="text-xs text-red-500 mt-1 animate-in fade-in duration-200">First name is required</p>
                  )}
                  {fieldErrors.firstName && <p className="text-sm text-red-500 mt-1">{fieldErrors.firstName}</p>}
                </div>
                <div className="space-y-2 animate-item stagger-3">
                  <Label htmlFor="lastName">Last Name</Label>
                  <div className="relative">
                    <Input
                      id="lastName"
                      value={lastName}
                      onChange={(e) => {
                        setLastName(e.target.value);
                        e.target.setCustomValidity('');
                      }}
                      onInvalid={(e) => {
                        (e.target as HTMLInputElement).setCustomValidity('Enter last name');
                      }}
                      className={`form-glass-input rounded-xl ${showValidation && !lastName.trim() ? 'border-red-500 focus:ring-red-500' : ''}`}
                      placeholder="Doe"
                      required
                    />
                  </div>
                  {showValidation && !lastName.trim() && (
                    <p className="text-xs text-red-500 mt-1 animate-in fade-in duration-200">Last name is required</p>
                  )}
                  {fieldErrors.lastName && <p className="text-sm text-red-500 mt-1">{fieldErrors.lastName}</p>}
                </div>
                <div className="space-y-2 animate-item stagger-4">
                  <Label htmlFor="email">Email</Label>
                  <div className="flex gap-3">
                    <div className="relative flex-1">
                      <Input
                        id="email"
                        type="email"
                        value={email}
                        onChange={(e) => {
                          handleEmailChange(e.target.value);
                          e.target.setCustomValidity('');
                        }}
                        onInvalid={(e) => {

                          const input = e.target as HTMLInputElement;
                          if (!input.value.trim()) {
                            input.setCustomValidity('Enter email');
                          } else if (!isEmailVerified) {
                            input.setCustomValidity('Verify email');
                          }
                        }}
                        onBlur={() => { /* validation happens on Send OTP click */ }}
                        className={`form-glass-input rounded-xl ${emailError || (showValidation && !email.trim())
                            ? 'border-red-500 focus:ring-red-500'
                            : emailValid
                              ? 'border-green-500'
                              : isEmailVerified
                                ? 'border-green-500'
                                : showValidation && email.trim() && !isEmailVerified
                                  ? 'border-red-500 focus:ring-red-500'
                                  : ''
                          } ${emailValidating || emailValid || isEmailVerified ? 'pr-10' : ''}`}
                        placeholder="john@example.com"
                        disabled={isEmailVerified}
                        required
                      />
                      {emailValidating && (
                        <div className="absolute right-3 top-1/2 -translate-y-1/2">
                          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                        </div>
                      )}
                      {emailValid && !emailValidating && !isEmailVerified && (
                        <div className="absolute right-3 top-1/2 -translate-y-1/2">
                          <CheckCircle2 className="h-4 w-4 text-green-500" />
                        </div>
                      )}
                      {isEmailVerified && (
                        <div className="absolute right-3 top-1/2 -translate-y-1/2">
                          <CheckCircle2 className="h-4 w-4 text-green-500" />
                        </div>
                      )}
                    </div>
                    <Button
                      type="button"
                      onClick={handleSendOtp}
                      disabled={!emailValid || emailValidating || isEmailVerified || otpSending}
                      className={`rounded-xl px-4 whitespace-nowrap transition-opacity duration-300 hover:brightness-100 hover:saturate-100 ${!emailValid || emailValidating || isEmailVerified || otpSending
                          ? 'btn-glass-primary opacity-50 cursor-not-allowed'
                          : 'btn-glass-primary'
                        }`}
                    >
                      {otpSending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : isEmailVerified ? (
                        'Verified'
                      ) : (
                        'Send OTP'
                      )}
                    </Button>
                  </div>
                  {emailError && (
                    <p className="text-xs text-red-500 mt-1 animate-in fade-in duration-200">
                      {emailError}
                    </p>
                  )}
                  {otpError && !isOtpModalOpen && (
                    <p className="text-xs text-red-500 mt-1 animate-in fade-in duration-200">
                      {otpError}
                    </p>
                  )}
                  {showValidation && !email.trim() && !emailError && (
                    <p className="text-xs text-red-500 mt-1 animate-in fade-in duration-200">Email is required</p>
                  )}
                  {showValidation && email.trim() && !isEmailVerified && !emailError && (
                    <p className="text-xs text-red-500 mt-1 animate-in fade-in duration-200">Please verify your email to continue</p>
                  )}
                  {fieldErrors.email && !emailError && (
                    <p className="text-sm text-red-500 mt-1">{fieldErrors.email}</p>
                  )}
                </div>

                {/* Divider - COMMENTED OUT FOR NOW */}
                {/* <div className="flex items-center gap-3 -my-1 animate-item stagger-5">
                  <div className="flex-1 h-px bg-border/50" />
                  <span className="text-xs text-muted-foreground font-medium">or</span>
                  <div className="flex-1 h-px bg-border/50" />
                </div> */}

                {/* Microsoft Sign-Up Button - COMMENTED OUT FOR NOW */}
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
                    {microsoftLoading ? 'Signing in...' : 'Sign up with Microsoft'}
                  </Button>
                </div> */}
              </div>
            )}

            {/* STEP 2: Company & Location */}
            {step === 2 && (
              <div className="space-y-4">
                <div className="space-y-2 animate-item stagger-2">
                  <Label htmlFor="company">Company (Optional)</Label>
                  <div className="relative">
                    <Input
                      id="company"
                      value={company}
                      onChange={(e) => {
                        setCompany(e.target.value);
                        e.target.setCustomValidity('');
                      }}
                      className="form-glass-input rounded-xl"
                      placeholder="Acme Corp"
                    />
                  </div>
                  {fieldErrors.company && <p className="text-sm text-red-500 mt-1">{fieldErrors.company}</p>}
                </div>
                <div className="space-y-2 animate-item stagger-3">
                  <Label htmlFor="location">Location (Optional)</Label>
                  <div className="relative">
                    <Input
                      id="location"
                      value={location}
                      onChange={(e) => {
                        setLocation(e.target.value);
                        e.target.setCustomValidity('');
                      }}
                      className="form-glass-input rounded-xl"
                      placeholder="New York"
                    />
                  </div>
                  {fieldErrors.location && <p className="text-sm text-red-500 mt-1">{fieldErrors.location}</p>}
                </div>
              </div>
            )}

            {/* STEP 3: Documents */}
            {step === 3 && (
              <div className="space-y-4">
                {/* Strategy Document Upload */}
                <div className="space-y-2 animate-item stagger-2">
                  <Label htmlFor="strategy">Strategy Document</Label>
                  <div className="relative hover:scale-[1.02] transition-all duration-300">
                    <Input
                      id="strategy"
                      value={strategy}
                      onChange={(e) => setStrategy(e.target.value)}
                      className="form-glass-input rounded-xl pr-12 hover:scale-100"
                      placeholder="Procurement Strategy"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-foreground transition-colors hover:bg-transparent transition-transform hover:scale-110 active:scale-95"
                      onClick={() => fileInputRef.current?.click()}
                      title="Upload Strategy Document"
                    >
                      <Upload className={`h-4 w-4 ${file ? "text-primary" : ""}`} />
                    </Button>
                    {/* Hidden File Input */}
                    <Input
                      type="file"
                      ref={fileInputRef}
                      className="hidden"
                      accept=".pdf,.docx,.doc,.txt,.png,.jpg,.jpeg,.csv"
                      onChange={handleFileChange}
                    />
                  </div>
                  {file && (
                    <div className="flex items-center justify-between text-xs text-muted-foreground mt-1 px-1">
                      <span>File: {file.name}</span>
                      <button type="button" onClick={removeFile} className="text-red-500 hover:text-red-700">Remove</button>
                    </div>
                  )}
                </div>

                {/* Standards Document Upload */}
                <div className="space-y-2 animate-item stagger-3">
                  <Label htmlFor="standards">Standards Document</Label>
                  <div className="relative hover:scale-[1.02] transition-all duration-300">
                    <Input
                      id="standards"
                      value={standardsFile ? standardsFile.name : ''}
                      readOnly
                      className="form-glass-input rounded-xl pr-12 hover:scale-100 cursor-pointer"
                      placeholder="Upload Standards Document"
                      onClick={() => standardsFileInputRef.current?.click()}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-foreground transition-colors hover:bg-transparent transition-transform hover:scale-110 active:scale-95"
                      onClick={() => standardsFileInputRef.current?.click()}
                      title="Upload Standards Document"
                    >
                      <Upload className={`h-4 w-4 ${standardsFile ? "text-primary" : ""}`} />
                    </Button>
                    {/* Hidden File Input */}
                    <Input
                      type="file"
                      ref={standardsFileInputRef}
                      className="hidden"
                      accept=".pdf,.docx,.doc,.txt,.png,.jpg,.jpeg"
                      onChange={handleStandardsFileChange}
                    />
                  </div>
                  {standardsFile && (
                    <div className="flex items-center justify-between text-xs text-muted-foreground mt-1 px-1">
                      <span>File: {standardsFile.name}</span>
                      <button type="button" onClick={removeStandardsFile} className="text-red-500 hover:text-red-700">Remove</button>
                    </div>
                  )}
                </div>

                {/* Assets Document Upload */}
                <div className="space-y-2 animate-item stagger-4">
                  <Label htmlFor="assets">Equipment/Assets List</Label>
                  <div className="relative hover:scale-[1.02] transition-all duration-300">
                    <Input
                      id="assets"
                      value={assetsFile ? assetsFile.name : ''}
                      readOnly
                      className="form-glass-input rounded-xl pr-12 hover:scale-100 cursor-pointer"
                      placeholder="Upload Equipment/Assets Document"
                      onClick={() => assetsFileInputRef.current?.click()}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-foreground transition-colors hover:bg-transparent transition-transform hover:scale-110 active:scale-95"
                      onClick={() => assetsFileInputRef.current?.click()}
                      title="Upload Equipment/Assets Document"
                    >
                      <Upload className={`h-4 w-4 ${assetsFile ? "text-primary" : ""}`} />
                    </Button>
                    {/* Hidden File Input */}
                    <Input
                      type="file"
                      ref={assetsFileInputRef}
                      className="hidden"
                      accept=".pdf,.csv,.docx,.xlsx,.txt"
                      onChange={handleAssetsFileChange}
                    />
                  </div>
                  {assetsFile && (
                    <div className="flex items-center justify-between text-xs text-muted-foreground mt-1 px-1">
                      <span>File: {assetsFile.name}</span>
                      <button type="button" onClick={removeAssetsFile} className="text-red-500 hover:text-red-700">Remove</button>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* STEP 4: Security */}
            {step === 4 && (
              <div className="space-y-4">
                <div className="space-y-2 animate-item stagger-1">
                  <Label htmlFor="username">Username</Label>
                  <div className="relative">
                    <Input
                      id="username"
                      value={username}
                      onChange={(e) => {
                        setUsername(e.target.value);
                        e.target.setCustomValidity('');
                        if (fieldErrors.username) setFieldErrors(prev => ({ ...prev, username: '' }));
                      }}
                      onInvalid={(e) => {
                        (e.target as HTMLInputElement).setCustomValidity('Enter username');
                      }}
                      className={`form-glass-input rounded-xl ${(showValidation && !username.trim()) || fieldErrors.username ? 'border-red-500 focus:ring-red-500' : ''}`}
                      placeholder="johndoe"
                      required
                    />
                  </div>
                  {showValidation && !username.trim() && (
                    <p className="text-xs text-red-500 mt-1 animate-in fade-in duration-200">Username is required</p>
                  )}
                  {fieldErrors.username && <p className="text-sm text-red-500 mt-1">{fieldErrors.username}</p>}
                </div>

                <div className="space-y-2 animate-item stagger-2">
                  <Label htmlFor="password">Password</Label>
                  <div className="relative hover:scale-[1.02] transition-all duration-300">
                    <Input
                      id="password"
                      type={showPassword ? 'text' : 'password'}
                      value={password}
                      pattern="^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$"
                      onChange={(e) => {
                        setPassword(e.target.value);
                        e.target.setCustomValidity('');
                        if (fieldErrors.password) setFieldErrors(prev => ({ ...prev, password: '' }));
                      }}
                      onInvalid={(e) => {
                        const input = e.target as HTMLInputElement;
                        if (!input.value) {
                          input.setCustomValidity('Enter password');
                        } else {
                          input.setCustomValidity('Password must be at least 8 chars, 1 uppercase, 1 lowercase, 1 number, 1 special symbol.');
                        }
                      }}
                      className={`form-glass-input pr-12 rounded-xl hover:scale-100 ${fieldErrors.password || (showValidation && !password) ? 'border-red-500 focus:ring-red-500' : ''}`}
                      placeholder="Create password"
                      required
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-foreground transition-colors hover:bg-transparent transition-transform hover:scale-110 active:scale-95"
                      onClick={() => setShowPassword(!showPassword)}
                    >
                      {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </Button>
                  </div>
                  {showValidation && !password && (
                    <p className="text-xs text-red-500 mt-1 animate-in fade-in duration-200">Password is required</p>
                  )}
                  {fieldErrors.password && <p className="text-sm text-red-500 mt-1">{fieldErrors.password}</p>}
                </div>

                <div className="space-y-2 animate-item stagger-3">
                  <Label htmlFor="confirmPassword">Confirm Password</Label>
                  <div className="relative hover:scale-[1.02] transition-all duration-300">
                    <Input
                      id="confirmPassword"
                      type={showConfirmPassword ? 'text' : 'password'}
                      value={confirmPassword}
                      onChange={(e) => {
                        setConfirmPassword(e.target.value);
                        e.target.setCustomValidity('');
                        if (fieldErrors.confirmPassword) setFieldErrors(prev => ({ ...prev, confirmPassword: '' }));
                      }}
                      onInvalid={(e) => {

                        const input = e.target as HTMLInputElement;
                        if (!input.value.trim()) {
                          input.setCustomValidity('Confirm password');
                        } else if (password !== confirmPassword) {
                          input.setCustomValidity("Passwords don't match");
                        }
                      }}
                      className={`form-glass-input pr-12 rounded-xl hover:scale-100 ${(showValidation && !confirmPassword) || (confirmPassword && password !== confirmPassword)
                          ? 'border-red-500 focus:ring-red-500'
                          : ''
                        }`}
                      placeholder="Confirm password"
                      required
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-foreground transition-colors hover:bg-transparent transition-transform hover:scale-110 active:scale-95"
                      onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    >
                      {showConfirmPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </Button>
                  </div>
                  {showValidation && !confirmPassword && (
                    <p className="text-xs text-red-500 mt-1 animate-in fade-in duration-200">Please confirm your password</p>
                  )}
                  {(confirmPassword && password !== confirmPassword) || fieldErrors.confirmPassword ? (
                    <p className="text-sm text-red-500 mt-1">
                      {fieldErrors.confirmPassword || 'Passwords do not match'}
                    </p>
                  ) : null}
                </div>
              </div>
            )}

            {/* Navigation Buttons */}
            <div className="flex justify-between items-center pt-4 animate-item stagger-6">
              {/* Left Button (Hidden on Step 1) */}
              <div className="w-1/3">
                {step > 1 && (
                  <Button type="button" variant="ghost" onClick={handlePrev} className="text-muted-foreground hover:text-foreground rounded-xl">
                    Previous
                  </Button>
                )}
              </div>

              {/* Step Indicators (Optional visual) */}
              <div className="flex gap-2">
                {[1, 2, 3, 4].map(i => (
                  <div key={i} className={`h-2 w-2 rounded-full transition-colors ${step === i ? 'bg-primary' : 'bg-gray-300/50'}`} />
                ))}
              </div>

              {/* Right Button (Next or Submit) */}
              <div className="w-1/3 flex justify-end">
                {step < 4 ? (
                  <Button
                    type="button"
                    onClick={handleNext}
                    className={`w-full font-semibold rounded-xl px-4 py-3 animate-item transition-opacity duration-300 hover:brightness-100 hover:saturate-100 ${(step === 1 && !isStep1Valid) ||
                        (step === 2 && !isStep2Valid) ||
                        (step === 3 && !isStep3Valid)
                        ? 'btn-glass-primary opacity-50'
                        : 'btn-glass-primary'
                      }`}
                  >
                    Next
                  </Button>
                ) : (
                  <Button
                    type="submit"
                    disabled={isLoading}
                    className={`rounded-xl px-8 py-3 h-auto font-semibold transition-opacity duration-300 hover:brightness-100 hover:saturate-100 ${isLoading ? 'btn-glass-primary opacity-50 cursor-not-allowed' : 'btn-glass-primary'}`}
                  >
                    {isLoading ? (
                      <div className="flex items-center gap-2">
                        <Loader2 className="h-5 w-5 animate-spin" />
                        <span>Creating...</span>
                      </div>
                    ) : (
                      'Sign Up'
                    )}
                  </Button>
                )}
              </div>
            </div>

            {/* Login Link */}
            <div className="text-center pt-2 animate-item stagger-7">
              <p className="text-muted-foreground text-sm">
                Already have an account?{' '}
                <Link
                  to="/login"
                  className="font-semibold group relative inline-block"
                >
                  <span className="relative z-10 text-secondary group-hover:text-primary transition-colors duration-200">
                    Sign in
                  </span>
                  <span className="absolute bottom-0 left-0 w-0 h-0.5 bg-primary group-hover:w-full transition-all duration-300 ease-out"></span>
                </Link>
              </p>
            </div>
          </form>
        </div>
      </div>
    </div>

        {/* OTP Verification Modal */}
        {isOtpModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-6 animate-in fade-in duration-200">
            <div className="max-w-sm w-full relative animate-in zoom-in-95 duration-300 acrylic-glass-pill p-6" style={{ backdropFilter: 'blur(80px)', backgroundColor: 'rgba(255, 255, 255, 0.40)' }}>
              {/* Close button */}
              <button
                onClick={handleCloseOtpModal}
                className="absolute top-5 right-5 text-muted-foreground hover:text-foreground transition-colors"
                title="Close"
              >
                <span className="text-lg">✕</span>
              </button>

              {/* Header */}
              <div className="text-center mb-4">
                <div className="w-12 h-12 mx-auto mb-3">
                  <Mail className="w-full h-full text-primary opacity-80" />
                </div>
                <h2 className="text-xl font-bold mb-1">Verify Your Email</h2>
                <p className="text-muted-foreground text-xs">
                  Code sent to <span className="font-semibold">{email}</span>
                </p>
              </div>

              {/* OTP Input */}
              <div className="space-y-3">
                <div className="space-y-2">
                  <Input
                    id="otp"
                    type="text"
                    maxLength={6}
                    value={otpCode}
                    onChange={(e) => {
                      const value = e.target.value.replace(/\D/g, ''); // Only digits
                      setOtpCode(value);
                      setOtpError('');
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && otpCode.length === 6) {
                        handleVerifyOtp();
                      }
                    }}
                    className="form-glass-input rounded-xl text-center text-xl tracking-[0.5em] font-mono"
                    placeholder="000000"
                    autoFocus
                  />
                  <p className="text-xs text-muted-foreground text-center">Expires in 10 minutes</p>
                </div>

                {/* Error Message */}
                {otpError && (
                  <p className="text-xs text-red-500 text-center">{otpError}</p>
                )}

                {/* Success Message */}
                {otpSuccess && (
                  <p className="text-xs text-green-500 text-center flex items-center justify-center gap-1">
                    <CheckCircle2 className="h-3 w-3" />
                    {otpSuccess}
                  </p>
                )}

                {/* Action Buttons */}
                <div className="flex gap-2 pt-1">
                  {/* Edit Email Button */}
                  <Button
                    type="button"
                    onClick={handleEditEmail}
                    variant="ghost"
                    className="flex-1 rounded-xl py-2.5 text-muted-foreground hover:text-foreground"
                  >
                    Edit Email
                  </Button>

                  {/* Verify Button */}
                  <Button
                    type="button"
                    onClick={handleVerifyOtp}
                    disabled={otpVerifying || otpCode.length !== 6}
                    className={`flex-1 rounded-xl py-2.5 font-semibold transition-opacity duration-300 hover:brightness-100 hover:saturate-100 ${otpVerifying || otpCode.length !== 6
                        ? 'btn-glass-primary opacity-50 cursor-not-allowed'
                        : 'btn-glass-primary'
                      }`}
                  >
                    {otpVerifying ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin mr-2" />
                        Verifying...
                      </>
                    ) : (
                      'Verify'
                    )}
                  </Button>
                </div>

                {/* Resend Link */}
                <div className="text-center pt-1">
                  <p className="text-xs">
                    <span className="text-foreground">Didn't receive? </span>
                    {resendTimer > 0 ? (
                      <span className="text-muted-foreground">Resend in {resendTimer}s</span>
                    ) : (
                      <button
                        type="button"
                        onClick={handleSendOtp}
                        disabled={otpSending}
                        className="font-semibold group relative inline-block disabled:opacity-50"
                      >
                        <span className="relative z-10 text-secondary group-hover:text-primary transition-colors duration-200">
                          {otpSending ? 'Sending...' : 'Resend'}
                        </span>
                        <span className="absolute bottom-0 left-0 w-0 h-0.5 bg-primary group-hover:w-full transition-all duration-300 ease-out"></span>
                      </button>
                    )}
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}
    </div>
  );
};

export default Signup;
