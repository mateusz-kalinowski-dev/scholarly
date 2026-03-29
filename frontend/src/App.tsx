import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Nav } from './components/Nav'
import { PapersPage } from './pages/PapersPage'
import { PaperDetailPage } from './pages/PaperDetailPage'
import { GraphPage } from './pages/GraphPage'
import { ScraperPage } from './pages/ScraperPage'
import './App.css'

function App() {
  return (
    <BrowserRouter>
      <Nav />
      <Routes>
        <Route path="/" element={<PapersPage />} />
        <Route path="/papers/:id" element={<PaperDetailPage />} />
        <Route path="/graph" element={<GraphPage />} />
        <Route path="/scraper" element={<ScraperPage />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
