import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import { SearchProvider } from './context/SearchContext.jsx'
import App from './App.jsx'
import './index.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <SearchProvider>
        <App />
        <Toaster
          position="bottom-right"
          toastOptions={{
            duration: 4000,
            style: { background: '#1f2937', color: '#f9fafb' },
          }}
        />
      </SearchProvider>
    </BrowserRouter>
  </StrictMode>,
)
