import { useLocation, Link } from "react-router-dom";
import { useEffect } from "react";
import { Compass, ArrowLeft, Home, Sparkles } from "lucide-react";

const NotFound = () => {
  const location = useLocation();

  useEffect(() => {
    console.error(
      "404 Error: User attempted to access non-existent route:",
      location.pathname
    );
  }, [location.pathname]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0d0d0d] text-white p-6 selection:bg-sky-500/30">
      <div className="max-w-md w-full text-center bg-[#171717] border border-white/10 rounded-2xl p-8 shadow-2xl backdrop-blur-xl">
        <div className="w-16 h-16 rounded-2xl bg-sky-500/10 border border-sky-500/30 flex items-center justify-center text-sky-400 mx-auto mb-5 shadow-lg">
          <Compass className="h-8 w-8 animate-pulse text-sky-400" />
        </div>
        <h1 className="text-5xl font-black text-white tracking-tight mb-2">404</h1>
        <h2 className="text-lg font-semibold text-zinc-200 mb-2">Page Not Found</h2>
        <p className="text-xs text-zinc-400 mb-6 leading-relaxed">
          The requested engineering module or route (<span className="text-sky-400 font-mono">{location.pathname}</span>) does not exist or has been relocated.
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
          <Link
            to="/chat"
            className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-sky-500 text-black font-semibold text-xs hover:bg-sky-400 transition-all shadow-md shadow-sky-500/20"
          >
            <Sparkles className="w-3.5 h-3.5" />
            Describe Copilot
          </Link>
          <Link
            to="/solution"
            className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-[#212121] hover:bg-[#2a2a2a] text-zinc-200 hover:text-white border border-white/10 text-xs font-medium transition-all"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            Solution Studio
          </Link>
        </div>
      </div>
    </div>
  );
};

export default NotFound;
