import { Routes, Route } from 'react-router-dom'
import Navbar from './components/Navbar.jsx'
import Home from './pages/Home.jsx'
import Results from './pages/Results.jsx'
import RestaurantDetail from './pages/RestaurantDetail.jsx'

export default function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/results" element={<Results />} />
        <Route path="/restaurant/:slug" element={<RestaurantDetail />} />
      </Routes>
    </div>
  )
}
