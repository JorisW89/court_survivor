import { Outlet } from 'react-router-dom'
import Navbar from './Navbar'

export default function Layout() {
  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <Navbar />
      <main className="max-w-5xl w-full mx-auto px-4 py-8 pb-24 md:pb-8 flex-1">
        <Outlet />
      </main>
      <footer className="text-center text-xs text-gray-400 py-4">
        Not affiliated with or endorsed by PSA World Tour.
      </footer>
    </div>
  )
}
