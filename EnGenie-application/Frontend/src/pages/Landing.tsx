import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  Building2,
  Package,
  BookOpen,
  Search,
  MessageSquare,
  CheckCircle,
  Shield,
  Grid,
  Wrench,
  ChevronRight,
  Linkedin,
  Twitter,
  Github,
  Brain,
  Zap,
  BarChart3,
  Loader2,
  Eye,
} from "lucide-react";
import axios from "axios";
import ScrollAnimation from "../components/ScrollAnimation";
import "../components/AIRecommender/api"; // ensure axios interceptors are initialized
import { useAuth } from "../contexts/AuthContext";

const Landing = () => {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const [isSupportOpen, setIsSupportOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [formData, setFormData] = useState({
    name: "",
    email: "",
    phone: "",
    message: "",
  });

  const [errors, setErrors] = useState<{
    name?: string;
    email?: string;
    phone?: string;
    message?: string;
  }>({});

  const [submitMessage, setSubmitMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  // Prevent background scroll when modal opens
  useEffect(() => {
    document.body.style.overflow = isSupportOpen ? "hidden" : "auto";
  }, [isSupportOpen]);

  // Handle input change
  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => {
    const { name, value } = e.target;

    setFormData({
      ...formData,
      [name]: value,
    });

    // Live validation
    let error = "";

    if (name === "name") {
      if (!value.trim()) error = "Please enter your name";
      else if (!/^[A-Za-z\s]+$/.test(value))
        error = "Enter a valid name (only letters)";
    }

    if (name === "email") {
      if (!value.trim()) error = "Please enter your email";
      else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value))
        error = "Enter a valid email address";
    }

    if (name === "phone") {
      if (!value.trim()) error = "Please enter your phone number";
      else if (!/^\d{10}$/.test(value))
        error = "Enter a valid 10-digit phone number";
    }

    if (name === "message") {
      if (!value.trim()) error = "Please enter your message";
    }

    setErrors((prev) => ({
      ...prev,
      [name]: error,
    }));
  };

  // Validation
  const validate = () => {
    const newErrors: {
      name?: string;
      email?: string;
      phone?: string;
      message?: string;
    } = {};

    // Name validation
    if (!formData.name.trim()) {
      newErrors.name = "Please enter your name";
    } else if (!/^[A-Za-z\s]+$/.test(formData.name)) {
      newErrors.name = "Enter a valid name (only letters)";
    }

    // Email validation
    if (!formData.email.trim()) {
      newErrors.email = "Please enter your email";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email)) {
      newErrors.email = "Enter a valid email address";
    } else if (/@(gmail|yahoo)\./i.test(formData.email)) {
      newErrors.email = "Enter your organization email address";
    }

    // Phone validation
    if (!formData.phone.trim()) {
      newErrors.phone = "Please enter your phone number";
    } else if (!/^\d{10}$/.test(formData.phone)) {
      newErrors.phone = "Enter a valid 10-digit phone number";
    }

    // Message validation
    if (!formData.message.trim()) {
      newErrors.message = "Please enter your message";
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // Submit
  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitMessage(null);

    if (validate()) {
      setIsSubmitting(true);

      try {
        const response = await axios.post(`/api/contact-form`, formData);

        if (response.data.success) {
          setSubmitMessage({
            type: "success",
            text: response.data.message || "Message submitted successfully!",
          });

          // Reset form
          setFormData({
            name: "",
            email: "",
            phone: "",
            message: "",
          });

          setErrors({
            name: "",
            email: "",
            phone: "",
            message: "",
          });

          // Close modal after 2 seconds
          setTimeout(() => {
            setIsSupportOpen(false);
            setSubmitMessage(null);
          }, 2000);
        } else {
          setSubmitMessage({
            type: "error",
            text: response.data.error || "Failed to send message. Please try again.",
          });
        }
      } catch (error: any) {
        console.error("Contact form error:", error);
        const errorMessage =
          error.response?.data?.error ||
          "Network error. Please check your connection and try again.";
        setSubmitMessage({
          type: "error",
          text: errorMessage,
        });
      } finally {
        setIsSubmitting(false);
      }
    }
  };

  const mainFeatures = [
    {
      image: "/icon-openbook-3d.webp",
      title: "Solution Engineering",
      description:
        "Turn a greenfield or brownfield requirement into a subsystem-by-subsystem Bill of Materials, tagged [INFERRED] or [STANDARDS] for full traceability.",
      benefits: [
        "Greenfield & brownfield requirement analysis",
        "Subsystem-level Bill of Materials generation",
        "[INFERRED] / [STANDARDS] parameter tagging",
        "Integration compatibility assessment",
      ],
      badge: "Multi-Vendor",
    },
    {
      image: "/icon-search-3d.webp",
      title: "Intelligent Search",
      description:
        "Compare a specific instrument across every catalog in our index in one pass, with transparent, parameter-level rationale instead of an opaque ranking.",
      benefits: [
        "Natural-language specification input",
        "Cross-vendor, standards-aware comparison",
        "Strategy-aware vendor filtering",
        "Transparent decision rationale",
      ],
      badge: "Multi-Vendor",
    },
    {
      image: "/icon-chat-3d.webp",
      title: "Quick Chat Assistant",
      description:
        "Instant, cited answers on instrumentation questions, grounded in your organizational standards, live search, and our indexed catalog.",
      benefits: [
        "Instant technical Q&A",
        "Product comparison guidance",
        "Scoped strictly to instrumentation topics",
        "Cited, standards-grounded answers",
      ],
      badge: "Cited Answers",
      badgeColor: "green",
    },
  ];

  const stats = [
    {
      value: "50–80%",
      label: "Less time spent on engineering specification",
    },
    {
      value: "$1.7M–$7.8M",
      label: "Value modeled per capital project",
    },
    { value: "6", label: "Manufacturer catalogs, one index" },
    { value: "2.8M", label: "Manufacturing retirements by 2033" },
  ];

  // Illustrative example shown in the Sample Output section
  const sampleBom = [
    {
      tag: "PT-4012",
      type: "Pressure Transmitter",
      spec: "0–600 psi, SIL 2, HART, Cl. I Div 2",
      recommended: "Rosemount 3051S",
      basis: "STANDARDS",
      pdfUrl:
        "https://productrecommener2.blob.core.windows.net/sample-outputs/PT-4012.pdf?se=2126-08-10T04%3A29%3A14Z&sp=r&sv=2026-02-06&sr=b&sig=qYP7N1uz3cB6TAKPLdUURuDG43GFBjSN53GrM%2BksDe0%3D",
    },
    {
      tag: "PT-4013",
      type: "Pressure Transmitter",
      spec: "0–600 psi, SIL 2, HART, Cl. I Div 2",
      recommended: "E+H Deltabar PMD75",
      basis: "INFERRED",
      pdfUrl:
        "https://productrecommener2.blob.core.windows.net/sample-outputs/PT-4013.pdf?se=2126-08-10T04%3A29%3A14Z&sp=r&sv=2026-02-06&sr=b&sig=QKo56Uu/HCiG9KMdTobliahLcZb8Bp3PFEIsYiQZ3PQ%3D",
    },
    {
      tag: "TT-4021",
      type: "Temperature Transmitter",
      spec: "-40–150°C, HART, dual head",
      recommended: "Rosemount 3144P",
      basis: "STANDARDS",
      pdfUrl:
        "https://productrecommener2.blob.core.windows.net/sample-outputs/TT-4021.pdf?se=2126-08-10T04%3A29%3A14Z&sp=r&sv=2026-02-06&sr=b&sig=rkxl8rfhnn79HrC66XCtcmyhWw2acSZ2XK3UMmWTp6E%3D",
    },
  ];

  const sampleComparison = [
    {
      vendor: "Emerson Rosemount 3051S",
      fit: "Full fit",
      full: true,
      rationale:
        "Matches SIL 2 and hazardous-area requirement; consistent with existing install base [STANDARDS: IEC 61511 loop integrity]",
    },
    {
      vendor: "Endress+Hauser Deltabar PMD75",
      fit: "Full fit",
      full: true,
      rationale:
        "Matches SIL 2 and hazardous-area requirement; broader turndown ratio [INFERRED from stated flow range]",
    },
    {
      vendor: "ABB 266HSH",
      fit: "Partial fit",
      full: false,
      rationale:
        "Meets pressure range; SIL 2 certification requires an optional module not in the stated configuration [STANDARDS: IEC 61508 certificate on file]",
    },
  ];

  const audiences = [
    {
      icon: Brain,
      eyebrow: "OT/ICS Consultants",
      title: "Scale Expert Judgment, Not Headcount",
      description:
        "Deliver audit-ready migration studies faster, with every parameter traced to a standard your client's reviewers can verify.",
      statValue: "110–180 hrs",
      statLabel: "Modeled hours returned on a 150-instrument, 2-vendor study",
      points: [
        "[INFERRED]/[STANDARDS] traceability for every recommendation",
        "One index across incumbent and candidate vendors",
      ],
    },
    {
      icon: Building2,
      eyebrow: "EPCs",
      title: "Turn Weeks of Specification Into Days",
      description:
        "Generate a standards-referenced BOM straight from project requirements.",
      statValue: "$1.7M–$7.8M",
      statLabel: "Modeled value per capital project",
      points: [
        "50–80% modeled reduction in specification hours",
        "Encoded expertise that outlives any one retirement",
      ],
    },
    {
      icon: Package,
      eyebrow: "OEMs & Automation Vendors",
      title: "Win a Fair Hearing, Every Time",
      description:
        "Get evaluated on transparent, standards-based criteria in every multi-vendor comparison.",
      statValue: "Same criteria",
      statLabel:
        "Every vendor scored on identical technical, compliance, and commercial factors",
      points: [
        "Embeddable procurement-intelligence module option",
        "Same ranking logic and data for every vendor, with or without OEM access",
      ],
    },
    {
      icon: Wrench,
      eyebrow: "System Integrators",
      title: "Quote Faster, Advise Higher",
      description:
        "Validate instrument choices against a customer's plant standards in minutes, not days.",
      statValue: "20–95 hrs",
      statLabel: "Modeled hours returned per 100-tag competitive bid",
      points: [
        "Strategy-aware filtering respects preferred-vendor agreements",
        "Faster bid-to-quote turnaround on competitive proposals",
      ],
    },
  ];

  const features = [
    {
      image: "/icon-brain-3d.webp",
      title: "One Multi-Vendor Index",
      description:
        "Six manufacturer catalogs standardized into a single index every recommendation reasons over.",
    },
    {
      image: "/icon-chart-3d.webp",
      title: "Standards-Aware Comparison",
      description:
        "Side-by-side scoring across technical fit, compliance, and commercial factors — the same criteria for every vendor.",
    },
    {
      image: "/icon-lightning-3d.webp",
      title: "Traceable, Not Opaque",
      description:
        "Every parameter tagged [INFERRED] or [STANDARDS] so your engineers can see exactly where it came from.",
    },
    {
      image: "/icon-shield-3d.webp",
      title: "Strategy-Aware Filtering",
      description:
        "Recommendations respect your preferred-supplier agreements and sourcing policy, with enterprise-grade security.",
    },
  ];

  const productTypes = [
    "Pressure Transmitter",
    "Temperature Transmitter",
    "Humidity Transmitter",
    "Flow Meter",
    "Level Transmitter",
    "pH Sensors",
  ];

  const steps = [
    {
      number: 1,
      title: "Describe the Requirement",
      description:
        "Type your spec in plain language — one instrument or a full subsystem, greenfield or brownfield.",
    },
    {
      number: 2,
      title: "Get a Traceable Recommendation",
      description:
        "The platform returns a multi-vendor BOM and comparison, with every parameter tagged [INFERRED] or [STANDARDS].",
    },
    {
      number: 3,
      title: "Review, Approve, Repeat",
      description:
        "Your engineers sign off — then reuse the same standards and vendor strategy on the next project.",
    },
  ];

  const benefits = [
    {
      icon: Shield,
      title: "Supplier Strategy Integration",
      description:
        "Recommendations align with your preferred supplier agreements and sourcing policy.",
    },
    {
      icon: Grid,
      title: "Configurable Standards Checks",
      description:
        "Specifications are checked against the codes and standards you configure — IEC 61511, IEC 61508, ATEX, SIL, NACE, API — and flagged for your review.",
    },
    {
      icon: Wrench,
      title: "Traceable, Not Opaque",
      description:
        "Every parameter is tagged [INFERRED] or [STANDARDS] so your engineers can see exactly where it came from.",
    },
  ];

  return (
    <div className="flex flex-col h-screen app-glass-gradient text-foreground overflow-hidden">
      {/* Decorative background images */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-[0] flex items-center justify-center">
          <img src="/engenie logo.jpeg" alt="" className="w-80 h-80 md:w-[32rem] md:h-[32rem] object-contain opacity-[0.04] select-none translate-y-8 md:translate-y-12" />
      </div>
      {/* Enhanced Header with Navigation */}
      <header className="glass-header flex-shrink-0">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-full overflow-hidden shadow-lg bg-white">
              <img src="/engenie logo.jpeg" alt="Logo" className="w-full h-full object-cover" />
            </div>
            <span className="text-2xl font-bold text-gradient-copilot">
              Copilot
            </span>
          </div>
          <nav className="hidden md:flex items-center gap-8">
            {[
              { label: "Platform", href: "#features" },
              { label: "Sample Output", href: "#sample-output" },
              { label: "How It Works", href: "#how-it-works" },
              { label: "Who We Serve", href: "#solutions" },
              { label: "Enquiry", href: "" },
            ].map(({ label: item, href }) =>
              item === "Enquiry" ? (
                <button
                  key={item}
                  onClick={() => setIsSupportOpen(true)}
                  className="text-sm font-medium hover:text-primary transition-colors relative group"
                >
                  {item}
                  <span className="absolute left-0 -bottom-1 w-0 h-0.5 bg-primary transition-all duration-300 group-hover:w-full"></span>
                </button>
              ) : (
                <a
                  key={item}
                  href={href}
                  className="text-sm font-medium hover:text-primary transition-colors relative group"
                >
                  {item}
                  <span className="absolute left-0 -bottom-1 w-0 h-0.5 bg-primary transition-all duration-300 group-hover:w-full"></span>
                </a>
              ),
            )}
          </nav>
          <div className="flex items-center gap-4">
            {isAuthenticated ? (
              <button
                className="btn-glass-primary px-6 py-2 rounded-full font-medium shadow-lg hover:shadow-xl"
                onClick={() => navigate("/chat")}
              >
                Go to Chat
              </button>
            ) : (
              <>
                <button
                  className="btn-glass-secondary px-6 py-2 rounded-full font-medium"
                  onClick={() => navigate("/login")}
                >
                  Login
                </button>
                <button
                  className="btn-glass-primary px-6 py-2 rounded-full font-medium shadow-lg hover:shadow-xl"
                  onClick={() => navigate("/signup")}
                >
                  Sign Up
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Main scrollable content */}
      <main className="flex-1 overflow-y-auto custom-visible-scrollbar-dark">
      {/* Hero Section */}
      <ScrollAnimation>
        <section className="pt-12 pb-6 md:pt-16 md:pb-20 px-6 max-w-7xl mx-auto">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            {/* Left Column: Text Content */}
            <div className="text-left space-y-8">
              <ScrollAnimation>
                <div className="inline-flex items-center gap-2 glass-pill mb-4">
                  <span className="w-2 h-2 bg-primary rounded-full animate-pulse"></span>
                  <span className="text-sm font-semibold text-primary">
                    Multi-Vendor AI Instrument Selection &amp; Specification
                    Platform
                  </span>
                </div>
                <h1 className="text-5xl md:text-6xl font-extrabold leading-[1.15] tracking-tight">
                  Specify the Right Instrument{" "}
                  <br className="hidden md:block" />
                  <span className="text-gradient-copilot leading-[1.3] pb-2 inline-block">
                    in Minutes, Not Weeks
                  </span>
                </h1>
                <p className="text-lg md:text-xl text-muted-foreground leading-relaxed max-w-xl mt-8">
                  The platform reasons across every manufacturer's catalog at once
                  and hands your engineers a ranked, traceable
                  recommendation—not another blank spec sheet. Less re-keying,
                  fewer errors, faster sign-off.
                </p>
                <div className="flex flex-col sm:flex-row gap-4 pt-4">
                  <button
                    className="btn-glass-primary px-8 py-4 text-lg rounded-full inline-flex items-center justify-center shadow-lg hover:shadow-xl hover:scale-105 transition-all"
                    onClick={() => navigate(isAuthenticated ? "/chat" : "/signup")}
                  >
                    {isAuthenticated ? "Open Chat" : "Get Started"}
                    <ChevronRight className="ml-2 w-5 h-5" />
                  </button>
                  <a
                    href="#sample-output"
                    className="px-8 py-4 text-lg rounded-full border-2 border-foreground/10 hover:bg-foreground/5 hover:border-foreground/30 transition-all font-semibold inline-flex items-center justify-center"
                  >
                    See a Sample Output
                  </a>
                </div>
              </ScrollAnimation>
            </div>

            {/* Right Column: Animated Visuals */}
            <div className="relative hidden lg:block h-[400px]">
              <ScrollAnimation className="h-full">
                {/* Very light background container */}
                <div className="absolute inset-0 bg-gradient-to-br from-slate-50 to-blue-50/20 rounded-3xl p-8 flex items-center justify-center">
                  {/* Dashboard Background - Glass Card */}
                  <div className="relative w-full h-full glass-card backdrop-blur-md rounded-2xl shadow-lg border border-white/50 p-8 flex flex-col gap-5">
                    {/* Header with Search Icon and Input Boxes */}
                    <div className="flex gap-3 items-center">
                      <div className="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center border border-blue-100">
                        <Search className="w-5 h-5 text-blue-500" />
                      </div>
                      <div className="flex-1 h-12 bg-slate-50 rounded-xl border border-gray-200"></div>
                      <div className="w-16 h-12 bg-slate-50 rounded-xl border border-gray-200"></div>
                    </div>

                    {/* Blue Progress Bar */}
                    <div className="w-1/3 h-6 bg-[#0F6CBD] rounded-lg"></div>

                    {/* Main Content Grid (2x2) - All Empty with Content Lines */}
                    <div className="grid grid-cols-2 gap-5 flex-1">
                      {/* Top Left */}
                      <div className="bg-slate-50/40 rounded-xl border border-gray-200/60 p-5 flex flex-col gap-3">
                        <div className="h-2.5 bg-gray-200 rounded w-3/4"></div>
                        <div className="h-2.5 bg-gray-200 rounded w-1/2"></div>
                      </div>

                      {/* Top Right */}
                      <div className="bg-slate-50/40 rounded-xl border border-gray-200/60 p-5 flex flex-col gap-3">
                        <div className="h-2.5 bg-gray-200 rounded w-2/3"></div>
                        <div className="h-2.5 bg-gray-200 rounded w-1/2"></div>
                      </div>

                      {/* Bottom Left */}
                      <div className="bg-slate-50/40 rounded-xl border border-gray-200/60 p-5 flex flex-col gap-3">
                        <div className="h-2.5 bg-gray-200 rounded w-3/5"></div>
                        <div className="h-2.5 bg-gray-200 rounded w-4/5"></div>
                      </div>

                      {/* Bottom Right - Empty (Standards Compliant will overlap this) */}
                      <div className="bg-slate-50/40 rounded-xl border border-gray-200/60 p-5 flex flex-col gap-3">
                        <div className="h-2.5 bg-gray-200 rounded w-2/3"></div>
                        <div className="h-2.5 bg-gray-200 rounded w-3/5"></div>
                      </div>
                    </div>
                  </div>

                  {/* Floating Card 1: Smart Search (Left Top) */}
                  <div className="absolute top-[12%] -left-8 glass-card backdrop-blur-md p-3.5 rounded-xl shadow-lg flex items-center gap-3 animate-float border border-white/50 z-20">
                    <div className="w-11 h-11 rounded-xl bg-blue-50 flex items-center justify-center flex-shrink-0 border border-blue-100">
                      <Search className="w-5 h-5 text-blue-500" />
                    </div>
                    <div>
                      <div className="font-semibold text-sm text-gray-900">
                        Smart Search
                      </div>
                      <div className="text-xs text-gray-500">
                        AI-powered discovery
                      </div>
                    </div>
                  </div>

                  {/* Floating Card 2: Quick Chat (Left Bottom) */}
                  <div className="absolute top-[55%] -left-6 glass-card backdrop-blur-md p-3.5 rounded-xl shadow-lg flex items-center gap-3 animate-float animation-delay-2000 border border-white/50 z-20">
                    <div className="w-11 h-11 rounded-xl bg-orange-50 flex items-center justify-center flex-shrink-0 border border-orange-100">
                      <MessageSquare className="w-5 h-5 text-orange-500" />
                    </div>
                    <div>
                      <div className="font-semibold text-sm text-gray-900">
                        Quick Chat
                      </div>
                      <div className="text-xs text-gray-500">
                        Instant answers
                      </div>
                    </div>
                  </div>

                  {/* Floating Card 3: Standards Compliant (Overlapping Bottom Right) */}
                  <div className="absolute bottom-12 -right-4 glass-card backdrop-blur-md p-3.5 rounded-xl shadow-lg flex items-center gap-3 animate-float animation-delay-4000 border border-white/50 z-20 min-w-[240px]">
                    <div className="w-11 h-11 rounded-xl bg-teal-50 flex items-center justify-center flex-shrink-0 border border-teal-100">
                      <Shield className="w-5 h-5 text-teal-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-sm text-gray-900">
                        Standards Compliant
                      </div>
                      <div className="text-xs text-gray-500">
                        Org policies built-in
                      </div>
                    </div>
                  </div>
                </div>
              </ScrollAnimation>
            </div>
          </div>
        </section>
      </ScrollAnimation>

      {/* Powerful AI-Driven Features Section */}
      <section className="pt-4 pb-16">
        <div className="max-w-7xl mx-auto px-6">
          <ScrollAnimation>
            <div className="text-center mb-16">
              <h2 className="text-4xl font-bold mb-4 text-gradient inline-block">
                Powerful AI-Driven Features
              </h2>
              <p className="text-lg text-muted-foreground">
                Experience the next generation of product recommendation
                technology
              </p>
            </div>
          </ScrollAnimation>

          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-8">
            {features.map((feature, index) => (
              <ScrollAnimation key={index}>
                <div className="glass-card p-6 group hover:scale-105 transition-transform duration-300 border-white/20 !bg-white/10 hover:!bg-white/20 h-full">
                  <div className="text-center">
                    <div className="mb-6 relative flex items-center justify-center transform transition-transform duration-300 group-hover:scale-110">
                      <img
                        src={feature.image}
                        alt={feature.title}
                        loading="lazy"
                        decoding="async"
                        className="w-24 h-24 object-contain mix-blend-multiply filter contrast-125 drop-shadow-xl"
                      />
                    </div>
                    <h3 className="text-lg font-semibold mb-2">
                      {feature.title}
                    </h3>
                  </div>
                  <div>
                    <p className="text-muted-foreground text-center text-sm leading-relaxed">
                      {feature.description}
                    </p>
                  </div>
                </div>
              </ScrollAnimation>
            ))}
          </div>
        </div>
      </section>

      {/* Stats Bar */}
      <section className="py-16 bg-gradient-to-br from-primary/10 to-secondary/10 backdrop-blur-sm">
        <div className="max-w-7xl mx-auto px-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
            {stats.map((stat, index) => (
              <ScrollAnimation key={index}>
                <div className="text-center">
                  <div className="text-3xl md:text-4xl font-extrabold text-gradient-copilot mb-2 whitespace-nowrap">
                    {stat.value}
                  </div>
                  <div className="text-sm text-muted-foreground font-medium">
                    {stat.label}
                  </div>
                </div>
              </ScrollAnimation>
            ))}
          </div>
        </div>
      </section>

      {/* Sample Output Section */}
      <section id="sample-output" className="py-16">
        <div className="max-w-6xl mx-auto px-6">
          <ScrollAnimation>
            <div className="text-center mb-10">
              <span className="inline-block glass-pill text-primary font-semibold mb-4">
                See It In Action
              </span>
              <h2 className="text-4xl md:text-5xl font-bold mb-4">
                What a Recommendation Actually Looks Like
              </h2>
              <p className="text-lg text-muted-foreground max-w-3xl mx-auto">
                A representative example of the kind of output the platform
                produces — from a stated requirement to a traceable,
                multi-vendor recommendation.
              </p>
            </div>
          </ScrollAnimation>

          <ScrollAnimation>
            <div className="rounded-xl bg-[#07365F] text-slate-100 px-6 py-5 text-sm leading-relaxed mb-8">
              &gt; &quot;Brownfield expansion, Unit 400 crude feed line. Need a
              pressure transmitter for custody-adjacent flow, SIL 2 loop, Class
              I Division 2, HART output, matching existing Rosemount install
              base where possible.&quot;
            </div>
          </ScrollAnimation>

          <ScrollAnimation>
            <div className="glass-card overflow-hidden mb-8">
              <div className="px-6 py-4 border-b border-border font-bold">
                Generated Subsystem BOM (excerpt)
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground bg-foreground/5">
                      <th className="px-4 py-3 font-semibold">Tag</th>
                      <th className="px-4 py-3 font-semibold">Type</th>
                      <th className="px-4 py-3 font-semibold">Key Spec</th>
                      <th className="px-4 py-3 font-semibold">Recommended</th>
                      <th className="px-4 py-3 font-semibold">Basis</th>
                      <th className="px-4 py-3"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {sampleBom.map((row) => (
                      <tr key={row.tag} className="border-t border-border transition-colors hover:bg-foreground/5">
                        <td className="px-4 py-3 font-medium whitespace-nowrap">
                          {row.tag}
                        </td>
                        <td className="px-4 py-3 text-muted-foreground">
                          {row.type}
                        </td>
                        <td className="px-4 py-3 text-muted-foreground">
                          {row.spec}
                        </td>
                        <td className="px-4 py-3 text-muted-foreground">
                          {row.recommended}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-block px-2.5 py-1 rounded-full text-[10px] font-bold ${
                              row.basis === "STANDARDS"
                                ? "bg-primary/15 text-primary"
                                : "bg-amber-100 text-amber-800"
                            }`}
                          >
                            {row.basis}
                          </span>
                        </td>
                        <td className="px-4 py-3 pr-8 text-right">
                          <a
                            href={row.pdfUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            aria-label={`View ${row.tag} sample output PDF`}
                            className="inline-flex text-muted-foreground hover:text-primary transition-colors"
                          >
                            <Eye className="w-4 h-4" />
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </ScrollAnimation>

          <ScrollAnimation>
            <div className="glass-card overflow-hidden">
              <div className="px-6 py-4 border-b border-border font-bold">
                Multi-Vendor Comparison — PT-4012
              </div>
              <div className="hidden md:grid grid-cols-[1.1fr_0.5fr_2fr] gap-4 px-6 py-3 bg-foreground/5 text-xs uppercase tracking-wide font-semibold text-muted-foreground">
                <div>Vendor / Model</div>
                <div>Fit</div>
                <div>Rationale</div>
              </div>
              {sampleComparison.map((row) => (
                <div
                  key={row.vendor}
                  className="grid md:grid-cols-[1.1fr_0.5fr_2fr] gap-2 md:gap-4 px-6 py-4 border-t border-border text-sm items-start transition-colors hover:bg-foreground/5"
                >
                  <div className="font-medium">{row.vendor}</div>
                  <div
                    className={`font-bold text-xs ${
                      row.full ? "text-emerald-600" : "text-amber-700"
                    }`}
                  >
                    {row.fit}
                  </div>
                  <div className="text-muted-foreground leading-relaxed">
                    {row.rationale}
                  </div>
                </div>
              ))}
            </div>
          </ScrollAnimation>
        </div>
      </section>

      {/* Who We Serve Section */}
      <section id="solutions" className="py-16">
        <div className="max-w-7xl mx-auto px-6">
          <ScrollAnimation>
            <div className="text-center mb-16">
              <span className="inline-block glass-pill text-primary font-semibold mb-4">
                Built For Your Role
              </span>
              <h2 className="text-4xl md:text-5xl font-bold mb-4">
                One Platform, Four Ways to Win
              </h2>
              <p className="text-lg text-muted-foreground max-w-3xl mx-auto">
                However you touch instrument specification, the platform gives you
                back the hours you lose to manual cross-referencing.
              </p>
            </div>
          </ScrollAnimation>

          <div className="grid md:grid-cols-2 gap-8">
            {audiences.map((audience, index) => (
              <ScrollAnimation key={index}>
                <div className="glass-card p-8 h-full border-l-4 border-primary hover:scale-[1.02] transition-all duration-300">
                  <div className="flex items-center gap-4 mb-5">
                    <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary to-secondary flex items-center justify-center shadow-lg flex-shrink-0">
                      <audience.icon className="w-7 h-7 text-white" />
                    </div>
                    <div>
                      <span className="block text-xs font-bold uppercase tracking-wider text-primary mb-1">
                        {audience.eyebrow}
                      </span>
                      <h3 className="text-xl md:text-2xl font-bold">
                        {audience.title}
                      </h3>
                    </div>
                  </div>
                  <p className="text-muted-foreground mb-5 leading-relaxed">
                    {audience.description}
                  </p>
                  <div className="rounded-xl border border-border bg-white/40 px-4 py-3 mb-5">
                    <span className="block text-lg font-extrabold text-primary">
                      {audience.statValue}
                    </span>
                    <span className="block text-xs text-muted-foreground mt-0.5">
                      {audience.statLabel}
                    </span>
                  </div>
                  <ul className="space-y-3">
                    {audience.points.map((point, idx) => (
                      <li key={idx} className="flex items-start gap-3">
                        <CheckCircle className="w-5 h-5 text-secondary flex-shrink-0 mt-0.5" />
                        <span className="text-sm">{point}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </ScrollAnimation>
            ))}
          </div>
        </div>
      </section>

      {/* Features Section - 3 Main Modules */}
      <section
        id="features"
        className="py-16 bg-gradient-to-br from-primary/5 to-secondary/5"
      >
        <div className="max-w-7xl mx-auto px-6">
          <ScrollAnimation>
            <div className="text-center mb-16">
              <span className="inline-block glass-pill text-primary font-semibold mb-4">
                The Platform
              </span>
              <h2 className="text-4xl md:text-5xl font-bold mb-4">
                Three Modules, One Shared Catalog
              </h2>
              <p className="text-lg text-muted-foreground max-w-3xl mx-auto">
                Solution, Search, and Quick Chat are the three ways you'll
                interact with the platform. All three reason over the same
                standardized, multi-vendor product index behind the scenes — you
                don't manage that index directly, it's the shared foundation
                every recommendation draws on.
              </p>
            </div>
          </ScrollAnimation>

          <div className="grid md:grid-cols-3 gap-8">
            {mainFeatures.map((feature, index) => (
              <ScrollAnimation key={index}>
                <div className="glass-card p-8 h-full hover:scale-[1.02] transition-all duration-300 flex flex-col group">
                  <div className="w-28 h-28 mx-auto flex items-center justify-center mb-2 transform transition-transform duration-300 group-hover:scale-110">
                    <img
                      src={feature.image}
                      alt={feature.title}
                      loading="lazy"
                      decoding="async"
                      className="w-full h-full object-contain mix-blend-multiply filter contrast-125 drop-shadow-xl"
                    />
                  </div>
                  <h3 className="text-2xl font-bold mb-4">{feature.title}</h3>
                  <p className="text-muted-foreground mb-6 leading-relaxed flex-grow">
                    {feature.description}
                  </p>
                  <ul className="space-y-3 mb-6">
                    {feature.benefits.map((benefit, idx) => (
                      <li key={idx} className="flex items-start gap-3">
                        <CheckCircle className="w-5 h-5 text-secondary flex-shrink-0 mt-0.5" />
                        <span className="text-sm">{benefit}</span>
                      </li>
                    ))}
                  </ul>
                  <div
                    className={`inline-flex items-center gap-2 px-4 py-2 rounded-full text-xs font-semibold ${feature.badgeColor === "green"
                        ? "bg-secondary/20 text-secondary"
                        : "bg-primary/20 text-primary"
                      }`}
                  >
                    {feature.badge}
                  </div>
                </div>
              </ScrollAnimation>
            ))}
          </div>
          <p className="mt-10 max-w-4xl mx-auto text-center text-sm text-muted-foreground leading-relaxed">
            Catalog coverage today: Honeywell, Emerson/Rosemount,
            Endress+Hauser, ABB, Siemens, and Yokogawa, concentrated in
            pressure, flow, level, and temperature instrumentation families,
            expanding over time. Coverage varies by manufacturer and product
            family — ask your representative for current scope against your
            instrument list.
          </p>
        </div>
      </section>

      {/* How It Works Section */}
      <section id="how-it-works" className="py-16 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-primary/10 to-secondary/10 backdrop-blur-3xl"></div>
        <div className="relative max-w-7xl mx-auto px-6">
          <ScrollAnimation>
            <div className="text-center mb-16">
              <span className="inline-block glass-pill text-secondary font-semibold mb-4">
                How It Works
              </span>
              <h2 className="text-4xl md:text-5xl font-bold mb-4">
                From Requirement to Ready-to-Order — in Three Steps
              </h2>
              <p className="text-lg text-muted-foreground max-w-3xl mx-auto">
                No lengthy setup. Describe what you need, and see a traceable
                answer the same day.
              </p>
            </div>
          </ScrollAnimation>

          <div className="grid md:grid-cols-3 gap-8">
            {steps.map((step, index) => (
              <ScrollAnimation key={index}>
                <div className="text-center relative">
                  <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-gradient-to-br from-primary to-secondary flex items-center justify-center text-white text-2xl font-bold shadow-lg">
                    {step.number}
                  </div>
                  {index < steps.length - 1 && (
                    <div className="hidden md:block absolute top-8 left-[60%] w-[80%] h-0.5 bg-gradient-to-r from-primary/50 to-transparent"></div>
                  )}
                  <h3 className="text-xl font-bold mb-3">{step.title}</h3>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    {step.description}
                  </p>
                </div>
              </ScrollAnimation>
            ))}
          </div>
        </div>
      </section>

      {/* Benefits Section */}
      <section id="benefits" className="py-16">
        <div className="max-w-7xl mx-auto px-6">
          <div className="grid md:grid-cols-2 gap-12 items-center">
            {/* Visual Side (Now on Left) */}
            <ScrollAnimation>
              <div className="relative rounded-3xl overflow-hidden shadow-2xl hover:scale-[1.02] transition-transform duration-500">
                <div className="w-full aspect-[4/3] bg-gradient-to-br from-[#0F6CBD] to-[#5FB3E6] p-8 md:p-12 flex items-center justify-center relative group">
                  {/* Main Glass Card */}
                  <div className="w-full h-full glass-card hover:bg-white/55 backdrop-blur-md border border-white/40 rounded-2xl p-6 md:p-8 flex flex-col gap-6 shadow-2xl relative overflow-hidden">
                    {/* Header Badge */}
                    <div className="inline-flex px-4 py-1.5 rounded-lg bg-white/80 backdrop-blur-md border border-white/60 self-start shadow-sm">
                      <span className="text-[#0F6CBD] font-bold text-sm">
                        Strategy Alignment
                      </span>
                    </div>

                    {/* Skeleton Content */}
                    <div className="space-y-4 flex-1">
                      {/* Row 1 - Glassy Content Box */}
                      <div className="bg-slate-50/40 backdrop-blur-sm rounded-xl p-4 space-y-3 border border-white/30 hover:scale-[1.02] transition-transform duration-300">
                        <div className="h-3 bg-gray-400/20 rounded w-1/3"></div>
                        <div className="h-2.5 bg-gray-400/20 rounded w-3/4"></div>
                      </div>

                      {/* Row 2 - Glassy Content Box */}
                      <div className="bg-slate-50/40 backdrop-blur-sm rounded-xl p-4 space-y-3 border border-white/30 hover:scale-[1.02] transition-transform duration-300">
                        <div className="h-3 bg-gray-400/20 rounded w-1/4"></div>
                        <div className="h-2.5 bg-gray-400/20 rounded w-2/3"></div>
                      </div>

                      {/* Row 3 - Selected Item (Active State) */}
                      <div className="bg-blue-50/80 backdrop-blur-md rounded-xl p-4 border border-[#0F6CBD]/50 flex items-center hover:scale-[1.02] transition-all duration-300 gap-4 shadow-sm">
                        <div className="flex-shrink-0">
                          <div className="w-8 h-8 rounded-full bg-[#0F6CBD] flex items-center justify-center shadow-sm">
                            <svg
                              className="w-5 h-5 text-white"
                              fill="none"
                              viewBox="0 0 24 24"
                              stroke="currentColor"
                              strokeWidth="3"
                            >
                              <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                d="M5 13l4 4L19 7"
                              />
                            </svg>
                          </div>
                        </div>
                        <div className="space-y-3 flex-1">
                          <div className="h-3 bg-[#0F6CBD]/20 rounded w-1/3"></div>
                          <div className="h-2.5 bg-[#0F6CBD]/10 rounded w-3/4"></div>
                        </div>
                        <div className="bg-[#0F6CBD] text-white text-[10px] font-bold px-3 py-1.5 rounded-md shadow-sm">
                          SELECT
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </ScrollAnimation>

            {/* Text Side (Now on Right) */}
            <ScrollAnimation>
              <div>
                <span className="inline-block glass-pill text-primary font-semibold mb-4">
                  How Standards Fit In
                </span>
                <h2 className="text-4xl md:text-5xl font-bold mb-6 text-foreground">
                  Standards-Referenced, Not Standards-Replacing
                </h2>
                <p className="text-lg text-muted-foreground mb-8 leading-relaxed">
                  The platform checks what you configure it to check, and shows its
                  work.
                </p>

                <div className="space-y-8">
                  {benefits.map((benefit, index) => (
                    <div key={index} className="flex gap-5">
                      <div className="w-12 h-12 rounded-xl bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center flex-shrink-0">
                        <benefit.icon className="w-6 h-6 text-primary" />
                      </div>
                      <div>
                        <h4 className="text-xl font-bold mb-2 text-foreground">
                          {benefit.title}
                        </h4>
                        <p className="text-muted-foreground leading-relaxed">
                          {benefit.description}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mt-8 rounded-xl bg-primary/10 px-6 py-4 text-sm text-muted-foreground leading-relaxed">
                  <strong className="text-foreground">
                    You stay in control:
                  </strong>{" "}
                  The platform surfaces the evidence and the rationale — your
                  engineers make the final call on every recommendation.
                </div>
              </div>
            </ScrollAnimation>
          </div>
        </div>
      </section>

      {/* Product Types Section */}
      <ScrollAnimation>
        <section className="py-16">
          <div className="relative max-w-7xl mx-auto px-6 text-center">
            <h2 className="text-3xl font-bold mb-3">
              Supported Product Categories
            </h2>
            <p className="text-base text-muted-foreground mb-8">
              Comprehensive analysis across various industrial sensor types
            </p>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              {productTypes.map((type, index) => (
                <div
                  key={index}
                  className="p-4 font-medium transition-all duration-300 text-base flex items-center justify-center min-h-[50px] hover:scale-102"
                  style={{
                    backgroundColor: "rgba(255, 255, 255, 0.35)",
                    backdropFilter: "blur(16px)",
                    WebkitBackdropFilter: "blur(16px)",
                    border: "1px solid rgba(255, 255, 255, 0.4)",
                    borderRadius: "0.75rem",
                    boxShadow: "0 4px 30px rgba(0, 0, 0, 0.15)",
                    transition: "all 0.3s ease",
                    cursor: "pointer",
                    width: "100%",
                    textAlign: "center",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor =
                      "rgba(255, 255, 255, 0.5)";
                    e.currentTarget.style.backdropFilter = "blur(20px)";
                    (e.currentTarget.style as any).WebkitBackdropFilter =
                      "blur(20px)";
                    e.currentTarget.style.borderColor =
                      "rgba(255, 255, 255, 0.6)";
                    e.currentTarget.style.transform = "scale(1.02)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor =
                      "rgba(255, 255, 255, 0.35)";
                    e.currentTarget.style.backdropFilter = "blur(16px)";
                    (e.currentTarget.style as any).WebkitBackdropFilter =
                      "blur(16px)";
                    e.currentTarget.style.borderColor =
                      "rgba(255, 255, 255, 0.4)";
                    e.currentTarget.style.transform = "scale(1)";
                  }}
                >
                  {type}
                </div>
              ))}
            </div>
          </div>
        </section>
      </ScrollAnimation>

      {/* CTA Section */}
      <ScrollAnimation>
        <section className="py-16 text-center">
          <div className="glass-card popup-blur-card p-12 max-w-4xl mx-auto border-white/30 !bg-white/15 hover:!bg-white/25 hover:shadow-2xl transition-all duration-300">
            <h2 className="text-4xl font-bold mb-6 text-gradient inline-block">
              Ready to Specify Smarter?
            </h2>
            <p className="text-xl text-muted-foreground mb-8 text-center max-w-2xl mx-auto">
              Create your account and run your next requirement through
              the platform — or log in if you're already registered.
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <button
                className="btn-glass-primary px-8 py-3 text-lg rounded-full inline-flex items-center justify-center shadow-lg hover:shadow-xl hover:scale-105 transition-all"
                onClick={() => navigate("/signup")}
              >
                Get Started
                <ChevronRight className="ml-2 w-5 h-5" />
              </button>
              <button
                className="btn-glass-secondary px-8 py-3 text-lg rounded-full shadow-md hover:shadow-lg hover:scale-105 transition-all"
                onClick={() => navigate("/login")}
              >
                Log In
              </button>
            </div>
          </div>
        </section>
      </ScrollAnimation>

      {/* Comprehensive Footer */}
      <footer
        id="contact"
        className="bg-gradient-to-br from-primary/10 to-secondary/10 backdrop-blur-sm border-t border-border"
      >
        <div className="max-w-7xl mx-auto px-6 py-12">
          <div className="grid md:grid-cols-3 lg:grid-cols-[2.4fr_1fr_1fr_1fr_1fr] gap-x-4 gap-y-8 mb-8">
            {/* Brand Column */}
            <div className="md:col-span-1">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-full overflow-hidden shadow-lg bg-white">
                  <img src="/engenie logo.jpeg" alt="Logo" className="w-full h-full object-cover" />
                </div>
                <span className="text-xl font-bold text-gradient-copilot">
                  Copilot
                </span>
              </div>
              <p className="text-sm text-muted-foreground leading-relaxed">
                A multi-vendor AI instrument selection &amp; specification
                platform for industrial process instrumentation — built for
                OT/ICS consultants, EPCs, OEMs &amp; automation vendors, and
                system integrators.
              </p>
            </div>

            {/* Solutions Column */}
            <div>
              <h4 className="font-bold mb-4">Platform</h4>
              <ul className="space-y-2 text-sm text-muted-foreground">
                {[
                  { label: "Solution Engineering", href: "#features" },
                  { label: "Intelligent Search", href: "#features" },
                  { label: "Quick Chat", href: "#features" },
                  { label: "Sample Output", href: "#sample-output" },
                  { label: "How It Works", href: "#how-it-works" },
                ].map((link) => (
                  <li key={link.label}>
                    <a
                      href={link.href}
                      className="hover:text-primary transition-colors"
                    >
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>

            {/* Who We Serve Column */}
            <div>
              <h4 className="font-bold mb-4">Who We Serve</h4>
              <ul className="space-y-2 text-sm text-muted-foreground">
                {[
                  "OT/ICS Consultants",
                  "EPCs",
                  "OEMs & Automation Vendors",
                  "System Integrators",
                ].map((label) => (
                  <li key={label}>
                    <a
                      href="#solutions"
                      className="hover:text-primary transition-colors"
                    >
                      {label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>

            {/* Company Column */}
            <div>
              <h4 className="font-bold mb-4">Company</h4>
              <ul className="space-y-2 text-sm text-muted-foreground">
                <li>
                  <a
                    href="https://ensarsolutions.com/about/"
                    target="_blabk"
                    className="hover:text-primary transition-colors"
                  >
                    About Ensar
                  </a>
                </li>
                <li>
                  <a href="#" className="hover:text-primary transition-colors">
                    Careers
                  </a>
                </li>
                <li>
                  <a
                    href="https://ensarsolutions.com/blog/"
                    target="_blank"
                    className="hover:text-primary transition-colors"
                  >
                    Blogs
                  </a>
                </li>
                <li>
                  <a
                    href="https://ensarsolutions.com/contact/"
                    target="_blank"
                    className="hover:text-primary transition-colors"
                  >
                    Contact Ensar
                  </a>
                </li>
              </ul>
            </div>

            {/* Resources Column */}
            <div>
              <h4 className="font-bold mb-4">Resources</h4>
              <ul className="space-y-2 text-sm text-muted-foreground">
                <li>
                  <a href="#" className="hover:text-primary transition-colors">
                    Documentation
                  </a>
                </li>
                <li>
                  <a href="#" className="hover:text-primary transition-colors">
                    {/* API Reference */}
                    Azure Market place(Coming soon)
                  </a>
                </li>
                <li>
                  <button
                    onClick={() => setIsSupportOpen(true)}
                    className="hover:text-primary transition-colors"
                  >
                    Support
                  </button>
                </li>
                <li>
                  <a href="#" className="hover:text-primary transition-colors">
                    Privacy Policy
                  </a>
                </li>
              </ul>
            </div>
          </div>

          {/* Footer Bottom */}
          <div className="pt-8 border-t border-border flex flex-col md:flex-row justify-between items-center gap-4">
            <p className="text-sm text-muted-foreground">
              © 2026. All rights reserved.
            </p>
            <div className="flex items-center gap-4">
              <a
                href="#"
                className="w-10 h-10 rounded-lg glass-card flex items-center justify-center hover:scale-110 transition-transform"
                aria-label="LinkedIn"
              >
                <Linkedin className="w-5 h-5 text-primary" />
              </a>
              <a
                href="#"
                className="w-10 h-10 rounded-lg glass-card flex items-center justify-center hover:scale-110 transition-transform"
                aria-label="Twitter"
              >
                <Twitter className="w-5 h-5 text-primary" />
              </a>
              <a
                href="#"
                className="w-10 h-10 rounded-lg glass-card flex items-center justify-center hover:scale-110 transition-transform"
                aria-label="GitHub"
              >
                <Github className="w-5 h-5 text-primary" />
              </a>
            </div>
          </div>
        </div>
      </footer>
      </main>

      {isSupportOpen && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center p-6 animate-in fade-in duration-200">
          <div
            className="w-full max-w-lg p-8 relative acrylic-glass-pill animate-in zoom-in-95 duration-300"
            style={{
              backdropFilter: "blur(80px)",
              backgroundColor: "rgba(255, 255, 255, 0.50)",
            }}
          >
            <button
              onClick={() => setIsSupportOpen(false)}
              className="absolute top-5 right-8 text-muted-foreground hover:text-foreground transition-colors"
              title="Close"
            >
              <span className="text-lg">✕</span>
            </button>

            <h2 className="text-2xl font-bold mb-6 text-center">
              Contact Support
            </h2>

            <form onSubmit={handleSubmit} className="space-y-4">
              {/* Name */}
              <div>
                <input
                  type="text"
                  name="name"
                  placeholder="Name"
                  value={formData.name}
                  onChange={handleChange}
                  className="form-glass-input rounded-xl w-full px-4 py-3"
                  disabled={isSubmitting}
                />
                {errors.name && (
                  <p className="text-red-500 text-xs mt-1">{errors.name}</p>
                )}
              </div>

              {/* Email */}
              <div>
                <input
                  type="email"
                  name="email"
                  placeholder="Email"
                  value={formData.email}
                  onChange={handleChange}
                  className="form-glass-input rounded-xl w-full px-4 py-3"
                  disabled={isSubmitting}
                />
                {errors.email && (
                  <p className="text-red-500 text-xs mt-1">{errors.email}</p>
                )}
              </div>

              {/* Phone */}
              <div>
                <input
                  type="tel"
                  name="phone"
                  maxLength={10}
                  placeholder="Phone"
                  value={formData.phone}
                  onChange={handleChange}
                  className="form-glass-input rounded-xl w-full px-4 py-3"
                  disabled={isSubmitting}
                />
                {errors.phone && (
                  <p className="text-red-500 text-xs mt-1">{errors.phone}</p>
                )}
              </div>

              {/* Message */}
              <div>
                <textarea
                  name="message"
                  placeholder="Message"
                  rows={4}
                  value={formData.message}
                  onChange={handleChange}
                  className="form-glass-input rounded-xl w-full px-4 py-3"
                  disabled={isSubmitting}
                />
                {errors.message && (
                  <p className="text-red-500 text-xs mt-1">{errors.message}</p>
                )}
              </div>

              {/* Success/Error Message */}
              {submitMessage && (
                <div
                  className={`text-xs text-center py-2 px-4 rounded-lg ${submitMessage.type === "success"
                      ? "bg-green-100 text-green-700"
                      : "bg-red-100 text-red-700"
                    }`}
                >
                  {submitMessage.text}
                </div>
              )}

              <button
                type="submit"
                disabled={isSubmitting}
                className={`w-full btn-glass-primary py-3 rounded-xl font-semibold transition-opacity duration-300 hover:brightness-100 hover:saturate-100 flex items-center justify-center gap-2 ${isSubmitting ? "opacity-50 cursor-not-allowed" : ""
                  }`}
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Sending...
                  </>
                ) : (
                  "Submit"
                )}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default Landing;
