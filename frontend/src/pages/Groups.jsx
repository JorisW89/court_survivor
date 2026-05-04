import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'

export default function Groups() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [groups, setGroups] = useState([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [joining, setJoining] = useState(false)
  const [newGroupName, setNewGroupName] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!user) return
    api.get('/groups')
      .then(r => setGroups(r.data))
      .finally(() => setLoading(false))
  }, [user])

  async function handleCreate(e) {
    e.preventDefault()
    if (!newGroupName.trim()) return
    setCreating(true)
    setError('')
    try {
      const { data } = await api.post('/groups', { name: newGroupName.trim() })
      navigate(`/groups/${data.id}`)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to create group')
      setCreating(false)
    }
  }

  async function handleJoin(e) {
    e.preventDefault()
    if (!inviteCode.trim()) return
    setJoining(true)
    setError('')
    try {
      const { data } = await api.post(`/groups/join/${inviteCode.trim()}`)
      navigate(`/groups/${data.id}`)
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid invite code')
      setJoining(false)
    }
  }

  if (!user) {
    return (
      <div className="card text-center py-12">
        <p className="text-gray-500 mb-3">Sign in to create or join groups.</p>
        <Link to="/login" className="btn-primary">Sign in</Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-900">My Groups</h1>

      {error && (
        <div className="bg-red-50 text-red-700 text-sm px-4 py-3 rounded-xl">{error}</div>
      )}

      <div className="grid sm:grid-cols-2 gap-4">
        {/* Create group */}
        <div className="card">
          <h2 className="font-semibold text-gray-900 mb-3">Create a group</h2>
          <form onSubmit={handleCreate} className="space-y-3">
            <input
              type="text"
              className="input"
              placeholder="Group name"
              value={newGroupName}
              onChange={e => setNewGroupName(e.target.value)}
              required
            />
            <button type="submit" disabled={creating} className="btn-primary w-full">
              {creating ? 'Creating…' : 'Create group'}
            </button>
          </form>
        </div>

        {/* Join group */}
        <div className="card">
          <h2 className="font-semibold text-gray-900 mb-3">Join a group</h2>
          <form onSubmit={handleJoin} className="space-y-3">
            <input
              type="text"
              className="input"
              placeholder="Invite code"
              value={inviteCode}
              onChange={e => setInviteCode(e.target.value)}
              required
            />
            <button type="submit" disabled={joining} className="btn-secondary w-full">
              {joining ? 'Joining…' : 'Join group'}
            </button>
          </form>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-8">
          <div className="animate-spin w-5 h-5 border-2 border-brand-500 border-t-transparent rounded-full" />
        </div>
      ) : groups.length === 0 ? (
        <div className="card text-center py-10">
          <p className="text-gray-400 text-sm">You haven't joined any groups yet.</p>
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 gap-4">
          {groups.map(group => (
            <Link
              key={group.id}
              to={`/groups/${group.id}`}
              className="card hover:shadow-md transition-shadow"
            >
              <h3 className="font-semibold text-gray-900">{group.name}</h3>
              <p className="text-sm text-gray-500 mt-1">{group.member_count} member{group.member_count !== 1 ? 's' : ''}</p>
              <p className="text-xs text-gray-400 mt-2 font-mono">{group.invite_code}</p>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
