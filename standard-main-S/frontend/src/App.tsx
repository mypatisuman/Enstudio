import { useState } from 'react'
import { Toaster } from 'sonner'
import Sidebar from './components/Sidebar'
import Topbar from './components/Topbar'
import HomeScreen from './components/screens/HomeScreen'
import ReviewScreen from './components/screens/ReviewScreen'
import ExportScreen from './components/screens/ExportScreen'
import IngestScreen from './components/screens/IngestScreen'
import CanvasScreen from './components/screens/CanvasScreen'
import DescribeScreen from './components/screens/DescribeScreen'
import ValidationScreen from './components/screens/ValidationScreen'
import { ExtractionProvider } from './state/ExtractionContext'
import { useAutoValidation } from './features/validation/useAutoValidation'
import { useAuth } from './state/useAuth'
import AuthScreen from './components/screens/AuthScreen'

// 'usage' is not a screen — usage/cost history is the UsageModal opened from
// the Topbar. The old UsageScreen was deleted when it moved to a modal.
export type Screen = 'home' | 'review' | 'canvas' | 'describe' | 'export' | 'validation' | 'ingest'

export interface Project {
  id: string
  name: string
  status: string
  instruments: number
  equipment: number
  drawings: number
  last_extraction: string | null
  last_activity: string | null
}

const FLUSH_SCREENS: Screen[] = ['canvas', 'describe']

function App() {
  const { user, loading } = useAuth()
  const [activeProject, setActiveProject] = useState<Project | null>(null)
  const [activeScreen, setActiveScreen] = useState<Screen>('home')

  // Pipeline step: auto-run + cache validation whenever an extraction finishes.
  useAutoValidation()

  // Gate the whole app behind auth. Restoring the session shows nothing briefly
  // (splash), then either the login screen or the real UI.
  if (loading) return <div style={{ height: '100vh', background: 'var(--bg-primary)' }} />
  if (!user) return <AuthScreen />

  function selectProject(p: Project | null) {
    setActiveProject(p)
    setActiveScreen('home')
  }

  function refreshProject(p: Project) {
    setActiveProject(p)
    // stay on current screen
  }

  const renderScreen = () => {
    switch (activeScreen) {
      case 'home': return <HomeScreen project={activeProject} setActiveScreen={setActiveScreen} setActiveProject={setActiveProject} />
      case 'review': return <ReviewScreen project={activeProject} setActiveScreen={setActiveScreen} />
      case 'export': return <ExportScreen project={activeProject} />
      case 'validation': return <ValidationScreen project={activeProject} setActiveScreen={setActiveScreen} />
      case 'ingest': return <IngestScreen project={activeProject} setActiveScreen={setActiveScreen} />
      case 'canvas': return <CanvasScreen project={activeProject} />
      case 'describe': return <DescribeScreen project={activeProject} setActiveScreen={setActiveScreen} />
    }
  }

  const isFlush = FLUSH_SCREENS.includes(activeScreen)

  return (
    <ExtractionProvider>
      <Toaster theme="dark" position="bottom-right" richColors />
      <div className="app-layout">
        <Sidebar
          activeProject={activeProject}
          setActiveProject={selectProject}
          refreshProject={refreshProject}
          activeScreen={activeScreen}
          setActiveScreen={setActiveScreen}
        />
        <div className="main-pane">
          <Topbar activeProject={activeProject} activeScreen={activeScreen} setActiveProject={selectProject} />
          <div className="content-row">
            <div className={isFlush ? 'screen-content-flush' : 'screen-content'}>
              {renderScreen()}
            </div>
          </div>
        </div>
      </div>
    </ExtractionProvider>
  )
}

export default App
