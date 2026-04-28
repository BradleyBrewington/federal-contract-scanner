import { Routes, Route, Navigate } from 'react-router-dom'
import Landing from './pages/Landing'
import Login from './pages/Login'
import AppShell from './pages/AppShell'

export default function App() {
  return (
    <Routes>
      <Route path="/"     element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/app"  element={<AppShell />} />
      <Route path="*"     element={<Navigate to="/" replace />} />
    </Routes>
  )
}
