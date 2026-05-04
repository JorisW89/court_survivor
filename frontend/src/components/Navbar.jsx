import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import SquashIcon from './SquashIcon'

export default function Navbar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  function handleLogout() {
    logout()
    navigate('/')
  }

  function isActive(path) {
    return location.pathname === path
  }

  return (
    <header className="bg-white border-b border-gray-100 sticky top-0 z-10">
      <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2">
          <SquashIcon className="w-5 h-5 text-brand-600" />
          <span className="font-semibold text-gray-900">Court Survivor</span>
        </Link>

        <nav className="flex items-center gap-1">
          {user ? (
            <>
              <Link
                to="/"
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive('/') ? 'bg-brand-50 text-brand-600' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                }`}
              >
                Games
              </Link>
              <Link
                to="/groups"
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  location.pathname.startsWith('/groups') ? 'bg-brand-50 text-brand-600' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                }`}
              >
                Groups
              </Link>
              <div className="ml-2 flex items-center gap-2">
                <span className="text-sm text-gray-500 hidden sm:block">{user.username}</span>
                <button
                  onClick={handleLogout}
                  className="text-sm text-gray-500 hover:text-gray-900 px-3 py-1.5 rounded-lg hover:bg-gray-50 transition-colors"
                >
                  Sign out
                </button>
              </div>
            </>
          ) : (
            <>
              <Link to="/login" className="text-sm text-gray-600 hover:text-gray-900 px-3 py-1.5 rounded-lg hover:bg-gray-50 transition-colors font-medium">
                Sign in
              </Link>
              <Link to="/register" className="btn-primary text-sm">
                Sign up
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  )
}
