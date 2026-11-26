import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Button } from '../components/ui/button';
import { CheckCircle, XCircle, ArrowLeft, Users, Shield, ChevronDown, UserCog, Coins, History, Loader2 } from 'lucide-react';
import { BASE_URL } from '../components/AIRecommender/api';
const API_BASE_URL = BASE_URL;

const AdminDashboard = () => {
  const { user, isLoading: authLoading, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  // Get parent path by removing /admin from current path
  const getParentPath = () => {
    // If navigated with state, use the 'from' path
    if (location.state?.from) {
      return location.state.from;
    }

    const path = location.pathname;
    if (path.endsWith('/admin')) {
      // Use slice to remove exactly '/admin' (6 characters) from the end
      const parentPath = path.slice(0, -6);
      return parentPath || '/chat';
    }
    return '/chat'; // default fallback
  };
  const [pendingUsers, setPendingUsers] = useState([]);
  const [allUsers, setAllUsers] = useState([]);
  const [dataLoading, setDataLoading] = useState(true);
  const [usersLoading, setUsersLoading] = useState(false);
  const [approvingIds, setApprovingIds] = useState(new Set());
  const [updatingRoleIds, setUpdatingRoleIds] = useState(new Set());
  const [error, setError] = useState(null);

  // State for view toggle
  const [activeView, setActiveView] = useState('pending'); // 'pending' or 'users'

  // State for modal
  const [modalOpen, setModalOpen] = useState(false);
  const [modalAction, setModalAction] = useState(null); // 'approve' or 'reject'
  const [modalUser, setModalUser] = useState(null); // user object for which modal is open

  // State for role dropdown
  const [openDropdownId, setOpenDropdownId] = useState(null); // which user's dropdown is open
  const [selectedRoles, setSelectedRoles] = useState({}); // { userId: 'admin' | 'user' }
  const dropdownRef = useRef(null);

  // State for credits management
  const [creditAccounts, setCreditAccounts] = useState({}); // { user_id(string): account }
  const [creditsLoading, setCreditsLoading] = useState(false);
  const [creditConfig, setCreditConfig] = useState(null); // { workflowCosts, enforcementEnabled }
  const [topupAmounts, setTopupAmounts] = useState({}); // { userId: string }
  const [applyingIds, setApplyingIds] = useState(new Set());
  const [expandedHistoryId, setExpandedHistoryId] = useState(null);
  const [historyRows, setHistoryRows] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setOpenDropdownId(null);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    if (!authLoading && (!isAuthenticated || user?.role !== 'admin')) {
      navigate('/');
    }
  }, [authLoading, isAuthenticated, user, navigate]);

  const fetchPendingUsers = async () => {
    setDataLoading(true);
    setError(null);
    try {
      const response = await axios.get('/api/admin/pending_users');
      setPendingUsers(response.data.pending_users || []);
    } catch (error) {
      console.error('Failed to fetch pending users:', error);
      setError(error.response?.data?.error || error.message);
      setPendingUsers([]);
    } finally {
      setDataLoading(false);
    }
  };

  const fetchAllUsers = async () => {
    setUsersLoading(true);
    try {
      const response = await axios.get('/api/admin/all_users');
      setAllUsers(response.data.users || []);
    } catch (error) {
      console.error('Failed to fetch all users:', error);
      setAllUsers([]);
    } finally {
      setUsersLoading(false);
    }
  };

  useEffect(() => {
    if (user?.role === 'admin') {
      fetchPendingUsers();
    }
  }, [user]);

  useEffect(() => {
    if (user?.role === 'admin' && activeView === 'users') {
      fetchAllUsers();
    }
  }, [user, activeView]);

  const fetchCreditsData = async () => {
    setCreditsLoading(true);
    try {
      const [usersRes, accountsRes] = await Promise.all([
        axios.get('/api/admin/all_users'),
        axios.get('/api/admin/credits/accounts?limit=200'),
      ]);
      setAllUsers(usersRes.data.users || []);
      const map = {};
      (accountsRes.data.accounts || []).forEach((acc) => {
        map[String(acc.user_id)] = acc;
      });
      setCreditAccounts(map);
      setCreditConfig({
        workflowCosts: accountsRes.data.workflow_costs || {},
        enforcementEnabled: !!accountsRes.data.enforcement_enabled,
      });
    } catch (error) {
      console.error('Failed to fetch credit accounts:', error);
      alert(`Failed to load credits: ${error.response?.data?.error || error.message}`);
    } finally {
      setCreditsLoading(false);
    }
  };

  useEffect(() => {
    if (user?.role === 'admin' && activeView === 'credits') {
      fetchCreditsData();
    }
  }, [user, activeView]);

  const fetchUserHistory = async (userId) => {
    setHistoryLoading(true);
    try {
      const res = await axios.get(`/api/admin/credits/history/${userId}?limit=10`);
      setHistoryRows(res.data.transactions || []);
    } catch (error) {
      console.error('Failed to fetch credit history:', error);
      setHistoryRows([]);
    } finally {
      setHistoryLoading(false);
    }
  };

  const toggleHistory = (userId) => {
    if (expandedHistoryId === userId) {
      setExpandedHistoryId(null);
      setHistoryRows([]);
    } else {
      setExpandedHistoryId(userId);
      setHistoryRows([]);
      fetchUserHistory(userId);
    }
  };

  const applyAdjustment = async (userId) => {
    const raw = String(topupAmounts[userId] || '').trim();
    const amount = parseInt(raw, 10);
    if (!raw || isNaN(amount) || amount === 0) {
      alert('Enter a non-zero whole number of credits (negative to deduct).');
      return;
    }
    setApplyingIds((prev) => new Set(prev).add(userId));
    try {
      const res = await axios.post('/api/admin/credits/topup', { user_id: userId, amount });
      const key = String(userId);
      setCreditAccounts((prev) => {
        const existing = prev[key] || { user_id: key, balance: 0, total_granted: 0, total_consumed: 0 };
        return { ...prev, [key]: { ...existing, balance: res.data.balance } };
      });
      setTopupAmounts((prev) => ({ ...prev, [userId]: '' }));
      if (expandedHistoryId === userId) {
        fetchUserHistory(userId);
      }
    } catch (error) {
      console.error('Failed to adjust credits:', error);
      alert(`Failed to adjust credits: ${error.response?.data?.error || error.message}`);
    } finally {
      setApplyingIds((prev) => {
        const newSet = new Set(prev);
        newSet.delete(userId);
        return newSet;
      });
    }
  };

  const toggleDropdown = (userId) => {
    if (openDropdownId === userId) {
      setOpenDropdownId(null);
    } else {
      setOpenDropdownId(userId);
      // Initialize with current role
      const currentUser = allUsers.find(u => u.id === userId);
      if (currentUser && !selectedRoles[userId]) {
        setSelectedRoles(prev => ({ ...prev, [userId]: currentUser.role }));
      }
    }
  };

  const selectRole = async (userId, role) => {
    const currentUser = allUsers.find(u => u.id === userId);

    // Don't update if role hasn't changed
    if (role === currentUser?.role) {
      setOpenDropdownId(null);
      return;
    }

    setSelectedRoles(prev => ({ ...prev, [userId]: role }));
    setUpdatingRoleIds(prev => new Set(prev).add(userId));
    setOpenDropdownId(null);

    try {
      await axios.post('/api/admin/update_role', { user_id: userId, role });

      // Update local state
      setAllUsers(prev => prev.map(u =>
        u.id === userId ? { ...u, role } : u
      ));
      // Clear selected role
      setSelectedRoles(prev => {
        const newState = { ...prev };
        delete newState[userId];
        return newState;
      });
    } catch (error) {
      console.error(`Failed to update user role:`, error);
      alert(`Failed to update role: ${error.response?.data?.error || error.message}`);
      // Revert selected role on error
      setSelectedRoles(prev => {
        const newState = { ...prev };
        delete newState[userId];
        return newState;
      });
    } finally {
      setUpdatingRoleIds(prev => {
        const newSet = new Set(prev);
        newSet.delete(userId);
        return newSet;
      });
    }
  };

  const performAction = async (userId, action) => {
    setApprovingIds(prev => new Set(prev).add(userId));
    setModalOpen(false);
    try {
      await axios.post('/api/admin/approve_user', { user_id: userId, action });
      setPendingUsers(prev => prev.filter(u => u.id !== userId));
    } catch (error) {
      console.error(`Failed to ${action} user:`, error);
      alert(`Failed to ${action} user: ${error.response?.data?.error || error.message}`);
    } finally {
      setApprovingIds(prev => {
        const newSet = new Set(prev);
        newSet.delete(userId);
        return newSet;
      });
    }
  };

  const openConfirmationModal = (user, action) => {
    setModalUser(user);
    setModalAction(action);
    setModalOpen(true);
  };

  if (authLoading || dataLoading) {
    return <div className="min-h-screen app-glass-gradient flex items-center justify-center text-foreground">Loading...</div>;
  }

  if (!user || user.role !== 'admin') {
    return null;
  }

  // Render User Management view
  // Count how many admins exist in the system
  const adminCount = allUsers.filter(u => u.role === 'admin').length;

  const renderUserManagement = () => (
    <div>
      <h3 className="text-xl font-semibold text-foreground mb-4">User Management</h3>
      {usersLoading ? (
        <p className="text-muted-foreground text-center">Loading users...</p>
      ) : allUsers.length === 0 ? (
        <p className="text-muted-foreground text-center">No users found.</p>
      ) : (
        <div className="space-y-4" style={{ isolation: 'auto' }}>
          {allUsers.map((userItem) => (
            <div
              key={userItem.id}
              className={`flex items-center justify-between gap-3 p-4 bg-gradient-to-br from-[#F5FAFC]/50 to-[#EAF6FB]/50 dark:from-slate-800/60 dark:to-slate-800/30 border border-white/30 dark:border-slate-700/30 rounded-xl hover:shadow-xl transition-all duration-300 hover:bg-white/20 dark:hover:bg-slate-800/40 hover:scale-[1.02] cursor-pointer relative ${openDropdownId === userItem.id ? 'z-[100]' : 'z-0'}`}
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className={`p-2 rounded-full flex-shrink-0 ${userItem.role === 'admin' ? 'bg-amber-100 dark:bg-amber-900/30' : 'bg-blue-100 dark:bg-blue-900/30'}`}>
                  {userItem.role === 'admin' ? (
                    <Shield className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                  ) : (
                    <Users className="w-5 h-5 text-blue-600 dark:text-blue-400" />
                  )}
                </div>
                <div className="min-w-0">
                  <p className="text-foreground font-medium truncate">{userItem.username}</p>
                  <p className="text-muted-foreground text-sm truncate">{userItem.email}</p>
                </div>
              </div>
              <div className="flex items-center gap-3 flex-shrink-0">
                <div className="relative" ref={openDropdownId === userItem.id ? dropdownRef : null} style={{ isolation: 'isolate' }}>
                  {/* Role toggle button — colour adapts to current role */}
                  <button
                    onClick={() => toggleDropdown(userItem.id)}
                    className={`flex items-center gap-2 px-4 py-2 rounded-lg border-2 transition-all shadow-sm hover:scale-105 ${
                      openDropdownId === userItem.id
                        ? (selectedRoles[userItem.id] || userItem.role) === 'admin'
                          ? 'border-amber-500 bg-amber-50 dark:bg-amber-900/20 shadow-md scale-105'
                          : 'border-[#0F6CBD] bg-blue-50 dark:bg-blue-900/20 shadow-md scale-105'
                        : 'border-gray-400 dark:border-slate-500 hover:border-gray-500 bg-white dark:bg-slate-800'
                    }`}
                  >
                    <span className={`text-sm font-medium ${
                      (selectedRoles[userItem.id] || userItem.role) === 'admin'
                        ? 'text-amber-700 dark:text-amber-400'
                        : 'text-blue-700 dark:text-blue-400'
                    }`}>
                      {(selectedRoles[userItem.id] || userItem.role) === 'admin' ? 'Admin' : 'User'}
                    </span>
                    <ChevronDown className={`w-4 h-4 text-gray-500 transition-transform ${openDropdownId === userItem.id ? 'rotate-180' : ''}`} />
                  </button>

                  {/* Dropdown menu - opens upward */}
                  {openDropdownId === userItem.id && (
                    <div className="absolute right-0 bottom-full mb-2 w-36 bg-white dark:bg-slate-800 rounded-2xl shadow-xl border border-gray-200 dark:border-slate-700 z-[200] p-2 flex flex-col gap-1">
                      {/* User option */}
                      <button
                        onClick={() => selectRole(userItem.id, 'user')}
                        disabled={userItem.id === user?.id && adminCount <= 1}
                        className={`w-full px-3 py-2 text-left text-sm rounded-xl transition-all duration-300 flex items-center gap-3
                          hover:bg-blue-50 dark:hover:bg-blue-900/20 hover:text-blue-700 dark:hover:text-blue-400 hover:scale-105 hover:shadow-md
                          disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100 disabled:hover:shadow-none disabled:hover:bg-transparent disabled:hover:text-gray-700 disabled:dark:hover:text-slate-300
                          ${
                            (selectedRoles[userItem.id] || userItem.role) === 'user'
                              ? 'text-blue-700 dark:text-blue-400 font-bold'
                              : 'text-gray-700 dark:text-slate-300'
                          }`}
                      >
                        <Users className="w-4 h-4 text-blue-600" />
                        <span className="font-medium">User</span>
                      </button>
                      {/* Admin option */}
                      <button
                        onClick={() => selectRole(userItem.id, 'admin')}
                        className={`w-full px-3 py-2 text-left text-sm rounded-xl transition-all duration-300 flex items-center gap-3
                          hover:bg-blue-50 dark:hover:bg-blue-900/20 hover:text-blue-700 dark:hover:text-blue-400 hover:scale-105 hover:shadow-md
                          ${
                            (selectedRoles[userItem.id] || userItem.role) === 'admin'
                              ? 'text-amber-700 dark:text-amber-400 font-bold'
                              : 'text-gray-700 dark:text-slate-300'
                          }`}
                      >
                        <Shield className="w-4 h-4 text-amber-600" />
                        <span className="font-medium">Admin</span>
                      </button>
                    </div>
                  )}
                </div>
                {userItem.id === user?.id && (
                  <span className="text-muted-foreground text-sm italic ml-1">(You)</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  const renderCreditsManagement = () => (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <h3 className="text-xl font-semibold text-foreground">Credits Management</h3>
        {creditConfig && (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="px-2 py-1 rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 font-medium">
              Solution run: {creditConfig.workflowCosts.solution ?? '—'} credits
            </span>
            <span className="px-2 py-1 rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 font-medium">
              Search run: {creditConfig.workflowCosts.search ?? '—'} credits
            </span>
            <span className={`px-2 py-1 rounded-full font-medium ${creditConfig.enforcementEnabled
              ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
              : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'}`}>
              {creditConfig.enforcementEnabled ? 'Enforcement ON' : 'Tracking only'}
            </span>
          </div>
        )}
      </div>
      {creditsLoading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-8 w-8 animate-spin text-[#0F6CBD]" />
        </div>
      ) : allUsers.length === 0 ? (
        <p className="text-muted-foreground text-center">No users found.</p>
      ) : (
        <div className="space-y-4">
          {allUsers.map((userItem) => {
            const account = creditAccounts[String(userItem.id)];
            const isApplying = applyingIds.has(userItem.id);
            const isExpanded = expandedHistoryId === userItem.id;
            return (
              <div key={userItem.id}>
                <div className="flex flex-wrap items-center justify-between gap-3 p-4 bg-gradient-to-br from-[#F5FAFC]/50 to-[#EAF6FB]/50 dark:from-slate-800/60 dark:to-slate-800/30 border border-white/30 dark:border-slate-700/30 rounded-xl hover:shadow-lg transition-all duration-300 hover:bg-white/20 dark:hover:bg-slate-800/40">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="p-2 rounded-full flex-shrink-0 bg-blue-100 dark:bg-blue-900/30">
                      <Coins className="w-5 h-5 text-[#0F6CBD] dark:text-blue-400" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-foreground font-medium truncate">
                        {userItem.username}
                        {userItem.id === user?.id && (
                          <span className="text-muted-foreground text-sm italic ml-1">(You)</span>
                        )}
                      </p>
                      <p className="text-muted-foreground text-sm truncate">{userItem.email}</p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-3 flex-shrink-0">
                    <div className="text-right mr-1">
                      <p className={`text-lg font-bold ${(account?.balance ?? 0) < 0 ? 'text-red-600 dark:text-red-400' : 'text-[#0F6CBD] dark:text-blue-400'}`}>
                        {account ? account.balance : 0}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {account ? `used ${account.total_consumed ?? 0}` : 'no activity yet'}
                      </p>
                    </div>
                    <input
                      type="number"
                      step="1"
                      placeholder="± credits"
                      value={topupAmounts[userItem.id] || ''}
                      onChange={(e) => setTopupAmounts((prev) => ({ ...prev, [userItem.id]: e.target.value }))}
                      onKeyDown={(e) => { if (e.key === 'Enter') applyAdjustment(userItem.id); }}
                      disabled={isApplying}
                      className="w-24 px-2 py-1.5 rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm text-foreground focus:outline-none focus:border-[#0F6CBD]"
                    />
                    <Button
                      size="sm"
                      onClick={() => applyAdjustment(userItem.id)}
                      disabled={isApplying || !String(topupAmounts[userItem.id] || '').trim()}
                      className="bg-[#0F6CBD] hover:bg-[#0d5ca3] text-white transition-transform hover:scale-105"
                    >
                      {isApplying ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Apply'}
                    </Button>
                    <button
                      onClick={() => toggleHistory(userItem.id)}
                      title="Recent credit activity"
                      className={`p-2 rounded-lg border transition-all hover:scale-105 ${isExpanded
                        ? 'border-[#0F6CBD] bg-blue-50 dark:bg-blue-900/20 text-[#0F6CBD]'
                        : 'border-gray-300 dark:border-slate-600 text-muted-foreground hover:text-foreground bg-white dark:bg-slate-800'}`}
                    >
                      <History className="w-4 h-4" />
                    </button>
                  </div>
                </div>
                {isExpanded && (
                  <div className="mx-4 mb-1 px-4 py-3 bg-white/60 dark:bg-slate-900/60 border border-t-0 border-white/30 dark:border-slate-700/30 rounded-b-xl">
                    {historyLoading ? (
                      <div className="flex items-center justify-center py-3">
                        <Loader2 className="h-5 w-5 animate-spin text-[#0F6CBD]" />
                      </div>
                    ) : historyRows.length === 0 ? (
                      <p className="text-muted-foreground text-sm text-center py-2">No credit activity for this user yet.</p>
                    ) : (
                      <div className="space-y-1">
                        {historyRows.map((txn, i) => (
                          <div key={`${txn.timestamp}-${i}`} className="flex flex-wrap items-center justify-between gap-2 text-sm py-1 border-b border-slate-100 dark:border-slate-800 last:border-0">
                            <span className="text-muted-foreground whitespace-nowrap">
                              {txn.timestamp ? new Date(txn.timestamp).toLocaleString() : '—'}
                            </span>
                            <span className="capitalize font-medium">
                              {txn.type}
                              {txn.workflow_type ? ` · ${txn.workflow_type}` : ''}
                            </span>
                            <span className="truncate max-w-[220px] text-muted-foreground">{txn.description || ''}</span>
                            <span className={`font-semibold ${txn.delta < 0 ? 'text-red-600 dark:text-red-400' : 'text-emerald-600 dark:text-emerald-400'}`}>
                              {txn.delta > 0 ? `+${txn.delta}` : txn.delta}
                            </span>
                            <span className="text-muted-foreground whitespace-nowrap">bal {txn.balance_after}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );

  return (
    <div className="h-screen app-glass-gradient text-foreground relative overflow-auto custom-visible-scrollbar-dark">
      {/* Subtle gradient background */}
      <div className="absolute inset-0 bg-gradient-to-br from-ai-primary/10 via-ai-primary/5 to-background"></div>

      {/* Fixed Header - matching MainHeader style */}
      <header className="glass-header px-6 py-4 fixed top-0 w-full z-50">
        <div className="flex items-center justify-between">
          {/* Left side - Logo */}
          <div className="w-16 h-16 rounded-full overflow-hidden shadow-lg border-2 border-white/50 bg-white">
            <img src="/engenie logo.jpeg" alt="Logo" className="w-full h-full object-cover" />
          </div>

          {/* Center - Title */}
          <div className="absolute left-1/2 transform -translate-x-1/2 text-center">
            <h1 className="text-3xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-[#0F6CBD] to-[#004E8C]">
              Admin Dashboard
            </h1>
          </div>

          {/* Right side - Empty for balance */}
          <div className="w-16"></div>
        </div>
      </header>

      {/* Main Content - with top padding for fixed header */}
      <div className="relative w-full max-w-6xl mx-auto pt-36 px-6 pb-6">
        {/* Top Actions */}
        <div className="flex flex-wrap items-center justify-between gap-3 mb-8">
          {/* View Toggle Buttons */}
          <div className="flex flex-wrap gap-2 sm:gap-4">
            <button
              onClick={() => setActiveView('pending')}
              className={`flex items-center gap-2 px-3 sm:px-6 py-2 sm:py-3 rounded-lg font-medium text-sm sm:text-base whitespace-nowrap transition-all ${activeView === 'pending'
                ? 'bg-[#0F6CBD] text-white shadow-lg'
                : 'bg-white/70 dark:bg-slate-800/70 text-foreground hover:bg-white dark:hover:bg-slate-800 border border-gray-200 dark:border-slate-700'
                }`}
            >
              <Users className="w-5 h-5" />
              Pending Users
            </button>
            <button
              onClick={() => setActiveView('users')}
              className={`flex items-center gap-2 px-3 sm:px-6 py-2 sm:py-3 rounded-lg font-medium text-sm sm:text-base whitespace-nowrap transition-all ${activeView === 'users'
                ? 'bg-[#0F6CBD] text-white shadow-lg'
                : 'bg-white/70 dark:bg-slate-800/70 text-foreground hover:bg-white dark:hover:bg-slate-800 border border-gray-200 dark:border-slate-700'
                }`}
            >
              <UserCog className="w-5 h-5" />
              User Management
            </button>
            <button
              onClick={() => setActiveView('credits')}
              className={`flex items-center gap-2 px-3 sm:px-6 py-2 sm:py-3 rounded-lg font-medium text-sm sm:text-base whitespace-nowrap transition-all ${activeView === 'credits'
                ? 'bg-[#0F6CBD] text-white shadow-lg'
                : 'bg-white/70 dark:bg-slate-800/70 text-foreground hover:bg-white dark:hover:bg-slate-800 border border-gray-200 dark:border-slate-700'
                }`}
            >
              <Coins className="w-5 h-5" />
              Credits
            </button>
          </div>

          {/* Back button */}
          <button
            onClick={() => navigate(getParentPath(), { replace: true })}
            className="flex items-center gap-2 px-3 sm:px-4 py-2 rounded-lg bg-white/70 dark:bg-slate-800/70 text-slate-700 hover:text-slate-900 border border-gray-200 dark:border-slate-700 dark:text-slate-400 dark:hover:text-slate-100 transition-all hover:scale-105 shadow-sm whitespace-nowrap"
            title="Go Back"
          >
            <ArrowLeft className="w-5 h-5" />
            <span className="hidden sm:inline font-medium">Back</span>
          </button>
        </div>

        {/* Content Area */}
        <div className="bg-white/50 dark:bg-slate-900/50 backdrop-blur-xl rounded-2xl p-8 border border-white/30 dark:border-slate-700/30 shadow-lg min-h-[100px] transition-all duration-300 hover:shadow-xl overflow-visible">

          {activeView === 'pending' && (
            <div>
              <h3 className="text-xl font-semibold text-foreground mb-4">Pending Users</h3>
              {error ? (
                <p className="text-ai-error text-center">{error}</p>
              ) : pendingUsers.length === 0 ? (
                <p className="text-muted-foreground text-center">No new users are pending approval.</p>
              ) : (
                <div className="space-y-4">
                  {pendingUsers.map((pendingUser) => (
                    <div
                      key={pendingUser.id}
                      className="flex items-center justify-between p-4 bg-gradient-to-br from-[#F5FAFC]/50 to-[#EAF6FB]/50 dark:from-slate-800/60 dark:to-slate-800/30 backdrop-blur-sm border border-white/30 dark:border-slate-700/30 rounded-xl hover:shadow-lg transition-all duration-300 hover:bg-white/20 dark:hover:bg-slate-800/40 hover:scale-[1.02]"
                    >
                      <div>
                        <p className="text-foreground font-medium">{pendingUser.username}</p>
                        <p className="text-muted-foreground text-sm">{pendingUser.email}</p>
                      </div>
                      <div className="flex gap-2">
                        <Button
                          onClick={() => openConfirmationModal(pendingUser, 'approve')}
                          disabled={approvingIds.has(pendingUser.id)}
                          className="bg-ai-success hover:bg-ai-success text-black transition-transform hover:scale-105"
                        >
                          <CheckCircle className="mr-2 h-4 w-4" />
                          Approve
                        </Button>
                        <Button
                          variant="ghost"
                          onClick={() => openConfirmationModal(pendingUser, 'reject')}
                          disabled={approvingIds.has(pendingUser.id)}
                          className="text-ai-error hover:text-red-700 hover:bg-transparent transition-transform hover:scale-105"
                        >
                          <XCircle className="mr-2 h-4 w-4" />
                          Reject
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeView === 'users' && renderUserManagement()}

          {activeView === 'credits' && renderCreditsManagement()}
        </div>
      </div>

      {/* Confirmation Modal for Approve/Reject */}
      {modalOpen && (
        <div className="fixed inset-0 flex items-center justify-center z-50 bg-black/70 backdrop-blur-md">
          <div className="rounded-2xl p-8 w-[380px] max-w-full text-center shadow-2xl border border-white/20 dark:border-slate-700/30 bg-gradient-to-br from-[#F5FAFC]/90 to-[#EAF6FB]/90 dark:from-slate-900/90 dark:to-slate-900/50 backdrop-blur-2xl text-foreground">
            <h2 className="text-2xl font-bold mb-4">
              Confirm {modalAction === 'approve' ? 'Approval' : 'Rejection'}
            </h2>
            <p className="mb-6 text-lg">
              Are you sure you want to {modalAction} <span className="font-bold">{modalUser?.username}</span>?
            </p>
            <div className="flex justify-center items-center gap-8 mt-6">
              <button
                onClick={() => setModalOpen(false)}
                className="text-muted-foreground hover:text-slate-900 dark:hover:text-slate-100 font-medium transition-transform hover:scale-125 bg-transparent border-none cursor-pointer"
              >
                Cancel
              </button>
              <button
                className={`font-semibold flex items-center gap-2 transition-transform hover:scale-125 bg-transparent border-none cursor-pointer ${modalAction === 'approve'
                  ? 'text-ai-success hover:text-green-700 dark:hover:text-green-400'
                  : 'text-ai-error hover:text-red-700 dark:hover:text-red-400'
                  }`}
                onClick={() => performAction(modalUser.id, modalAction)}
                disabled={approvingIds.has(modalUser.id)}
              >
                {modalAction === 'approve' ? (
                  <>
                    <CheckCircle className="inline mr-1 h-5 w-5" /> Approve
                  </>
                ) : (
                  <>
                    <XCircle className="inline mr-1 h-5 w-5" /> Reject
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}



    </div>
  );
};

export default AdminDashboard;
