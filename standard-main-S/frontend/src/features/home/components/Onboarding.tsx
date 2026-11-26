import { useState, useEffect, type ReactNode } from 'react'
import { FolderOpen, Sparkles, Upload, FilePlus2, LayoutGrid, Network, CheckCircle2, Wand2, ShieldCheck, ArrowRight, Download } from 'lucide-react'
import { listProjects, getProjectStats } from '../../../services/project'
import { storedUserId } from '../../../services/authApi'
import { ProjectPickerModal } from './ProjectPickerModal'
import { StepsModal } from './StepsModal'
import { RightPanel } from '../../rightpanel/RightPanel'
import type { Project, Screen } from '../../../App'

const GS_STEPS: { title: string; sub: string; icon: ReactNode }[] = [
  { title: 'Upload', sub: 'Upload drawing or PDF', icon: <Upload size={22} /> },
  { title: 'Extract', sub: 'AI extracts instruments & equipment', icon: <Wand2 size={22} /> },
  { title: 'Review', sub: 'Review and validate extracted data', icon: <CheckCircle2 size={22} /> },
  { title: 'Canvas', sub: 'Visualize & build connections', icon: <Network size={22} /> },
  { title: 'Export', sub: 'Export reports & deliverables', icon: <Download size={22} /> },
]

const QUICK_ACTIONS: { title: string; desc: string; icon: ReactNode; screen: Screen; newProject?: boolean; picker?: 'open' | 'canvas' | 'upload' }[] = [
  { title: 'Create Project', desc: 'Start a new extraction', icon: <FilePlus2 size={20} />, screen: 'ingest', newProject: true },
  { title: 'Upload P&ID', desc: 'Upload PDF files and drawings', icon: <Upload size={20} />, screen: 'ingest', picker: 'upload' },
  { title: 'Open Project', desc: 'Continue from where you left', icon: <FolderOpen size={20} />, screen: 'home', picker: 'open' },
  { title: 'Explore Canvas', desc: 'Visualize & edit P&ID on canvas', icon: <LayoutGrid size={20} />, screen: 'canvas', picker: 'canvas' },
]

function HeroStat({ icon, value, title, sub }: { icon: ReactNode; value: number | string; title: string; sub?: string }) {
  return (
    <div className="hero-stat">
      <span className="hero-stat__icon">{icon}</span>
      <div className="hero-stat__value">{value}</div>
      <div className="hero-stat__title">{title}</div>
      {sub && <div className="hero-stat__sub">{sub}</div>}
    </div>
  )
}

export function Onboarding({ setActiveScreen, setActiveProject }: {
  setActiveScreen: (s: Screen) => void
  setActiveProject: (p: Project | null) => void
}) {
  const [projects, setProjects] = useState<Project[]>([])
  const [picker, setPicker] = useState<null | 'open' | 'canvas' | 'upload'>(null)
  const [showSteps, setShowSteps] = useState(false)
  const [avgQuality, setAvgQuality] = useState<number | null>(null)

  useEffect(() => {
    listProjects(storedUserId()).then(setProjects).catch(() => { })
  }, [])

  // Real average extraction quality (edge/node ratio) across all projects —
  // same metric used per-project in the Recent Projects panel.
  useEffect(() => {
    let alive = true
    if (projects.length === 0) { setAvgQuality(null); return }
    Promise.all(projects.map(p => getProjectStats(p.id).catch(() => null))).then(all => {
      if (!alive) return
      const pcts = all
        .filter((s): s is NonNullable<typeof s> => s != null && s.node_count > 0)
        .map(s => Math.min(s.edge_count / s.node_count / 1.2, 1) * 100)
      setAvgQuality(pcts.length ? Math.round(pcts.reduce((a, b) => a + b, 0) / pcts.length) : null)
    })
    return () => { alive = false }
  }, [projects])

  // Real aggregates across the user's projects.
  const projectCount = projects.length
  const extractedCount = projects.filter(p => p.status === 'extracted' || p.status === 'reviewed').length

  return (
    <div className="home-hero-wrap home-landing">
      <style>{HERO_CSS}</style>

      <div className="home-landing__main">

      {/* ── Hero: text + stats (left) · engine artwork (right) ── */}
      <div className="ai-hero ai-hero--split">
        <div className="ai-hero__left">
          <div className="ai-hero__eyebrow">Welcome to</div>
          <h1 className="ai-hero__title"><span className="tf-en">en</span>STUDIO</h1>
          <p className="ai-hero__desc">AI-powered P&amp;ID extraction and process engineering toolkit.</p>

          <div className="ai-hero__stats">
            <HeroStat icon={<FolderOpen size={18} />} value={projectCount} title="Projects" />
            <HeroStat icon={<Sparkles size={18} />} value={extractedCount} title="Extractions" />
            <HeroStat icon={<ShieldCheck size={18} />} value={avgQuality != null ? `${avgQuality}%` : '—'} title="Quality" />
          </div>
        </div>
        <div className="ai-hero__art" aria-hidden="true" />
      </div>

      {/* ── Quick actions ── */}
      <section className="home-section">
        <div className="home-sec-head"><h2 className="home-sec-title">Quick actions</h2></div>
        <div className="qa-grid">
          {QUICK_ACTIONS.map(a => (
            <button
              key={a.title}
              className="qa-card"
              onClick={() =>
                a.newProject ? window.dispatchEvent(new Event('enstudio:new-project'))
                  : a.picker ? setPicker(a.picker)
                    : setActiveScreen(a.screen)
              }
            >
              <span className="qa-card__icon">{a.icon}</span>
              <span className="qa-card__title">{a.title}</span>
              <span className="qa-card__desc">{a.desc}</span>
              <span className="qa-card__arrow"><ArrowRight size={16} /></span>
            </button>
          ))}
        </div>
      </section>

      {/* ── Workflow (horizontal step tracker) ── */}
      <section className="home-section">
        <div className="home-sec-head">
          <h2 className="home-sec-title">Workflow</h2>
          <button className="home-sec-link" onClick={() => setShowSteps(true)}>View all steps</button>
        </div>
        <div className="gs-workflow-card">
          <div className="gs-track">
            {GS_STEPS.map((s, i) => (
              <div className="gs-step" key={i}>
                <span className="gs-step__icon">{s.icon}</span>
                <div className="gs-step__top">
                  <span className="gs-step__label">{s.title}</span>
                </div>
                <div className="gs-step__sub">{s.sub}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      </div>{/* .home-landing__main */}

      {/* ── Right column: recent projects + latest activity (was the dock) ── */}
      <aside className="home-landing__dock">
        <RightPanel activeProject={null} setActiveProject={setActiveProject} />
      </aside>

      {picker && (
        <ProjectPickerModal
          title={picker === 'canvas' ? 'Explore Canvas — select a project'
            : picker === 'upload' ? 'Upload P&ID — select a project'
              : 'Open a project'}
          projects={projects}
          onPick={p => {
            setActiveProject(p)
            setActiveScreen(picker === 'canvas' ? 'canvas' : picker === 'upload' ? 'ingest' : 'home')
            setPicker(null)
          }}
          onCancel={() => setPicker(null)}
        />
      )}

      {showSteps && <StepsModal onCancel={() => setShowSteps(false)} />}
    </div>
  )
}

const HERO_CSS = `
.home-hero-wrap { display: flex; flex-direction: column; gap: 18px; }

/* Landing = main content (left) + recent/activity dock (right column). */
.home-landing { display: grid; grid-template-columns: minmax(0,1fr) 320px; gap: 24px; align-items: start; }
.home-landing__main { display: flex; flex-direction: column; gap: 18px; min-width: 0; }
@media (max-width: 1100px) { .home-landing { grid-template-columns: 1fr; } }

.ai-hero {
  --h-primary: #1E7BFF;
  --h-secondary: #3F96FF;
  --h-highlight: #66B7FF;
  --h-glow: rgba(37,130,255,.35);
  --h-wire: rgba(37,130,255,.18);
  position: relative;
  border-radius: var(--r-lg);
  overflow: hidden;
  background: radial-gradient(120% 120% at 78% 30%, #071425 0%, #040814 72%);
  border: 1px solid rgba(37,130,255,.14);
  box-shadow: var(--shadow-card), inset 0 1px 0 rgba(102,183,255,.08);
  isolation: isolate;
}
.ai-hero--split {
  position: relative;
  display: flex;
  align-items: center;
  min-height: 280px;
  padding: 20px 36px;
  background: #050A14;
}
/* Engine artwork confined to the right; left edge fades into the dark card so
   the text/stats stay on clean space (like the reference). */
.ai-hero__art {
  position: absolute; top: 0; right: 0; bottom: 0;
  width: 60%; z-index: 1;
  background: url('/hero.png') center / cover no-repeat;
}
/* Fade the left edge deep into the dark so the title + stat cards stay on clean space. */
.ai-hero__art::before {
  content: '';
  position: absolute; inset: 0;
  background: linear-gradient(90deg, #050A14 0%, rgba(5,10,20,.94) 20%, rgba(5,10,20,.45) 44%, rgba(5,10,20,0) 64%);
}
@media (prefers-reduced-motion: reduce) { .ai-hero__art { animation: none; } }
/* ── Content ── */
.ai-hero__left { position: relative; z-index: 2; display: flex; flex-direction: column; max-width: 560px; }
.ai-hero__eyebrow { font-size: 15px; font-weight: 500; color: var(--text-secondary); margin-bottom: 2px; }
.ai-hero__title {
  margin: 0; font-size: 44px; font-weight: 800; line-height: 1.02;
  letter-spacing: -0.02em; color: #fff;
}
.ai-hero__title .tf-en { color: var(--h-primary); }
.ai-hero__desc { margin: 10px 0 0; font-size: 14px; line-height: 1.55; color: var(--text-secondary); max-width: 380px; }

.ai-hero__stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 18px; max-width: 440px; }
.hero-stat {
  min-width: 0;
  background: var(--bg-glass);
  backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: 12px 13px 11px;
  box-shadow: var(--glass-hi);
  transition:
    transform .35s cubic-bezier(.22,1,.36,1),
    border-color .35s cubic-bezier(.22,1,.36,1),
    box-shadow .35s cubic-bezier(.22,1,.36,1),
    background-color .35s cubic-bezier(.22,1,.36,1);
}
.hero-stat:hover { transform: translateY(-6px) scale(1.015); border-color: var(--border-bright); background: var(--bg-glass-hi); box-shadow: var(--shadow-lg), var(--glass-hi); }
.hero-stat__icon {
  display: inline-flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; border-radius: 9px; margin-bottom: 9px;
  color: var(--accent-bright);
  background: rgba(30,123,255,.14); border: 1px solid var(--accent-border);
  transition: transform .35s cubic-bezier(.22,1,.36,1);
}
.hero-stat:hover .hero-stat__icon { transform: scale(1.08); }
.hero-stat__value { font-size: 24px; font-weight: 800; color: #fff; line-height: 1; font-variant-numeric: tabular-nums; }
.hero-stat__title { font-size: 12.5px; font-weight: 600; color: var(--text-primary); margin-top: 7px; }
.hero-stat__sub { font-size: 10.5px; color: var(--text-muted); margin-top: 2px; }

@media (max-width: 720px) {
  .ai-hero__stats { grid-template-columns: 1fr; max-width: 220px; }
}
@media (prefers-reduced-motion: reduce) {
  .hero-stat, .hero-stat__icon { transition: none; }
  .hero-stat:hover, .hero-stat:hover .hero-stat__icon { transform: none; }
}
`
