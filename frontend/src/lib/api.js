import { supabase } from './supabase'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:5001'

async function authHeaders() {
  const { data: { session } } = await supabase.auth.getSession()
  if (!session) return {}
  return { Authorization: `Bearer ${session.access_token}` }
}

async function get(path) {
  const headers = await authHeaders()
  const res = await fetch(`${API_BASE}${path}`, { headers })
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`)
  return res.json()
}

async function post(path, body = {}) {
  const headers = { 'Content-Type': 'application/json', ...(await authHeaders()) }
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`)
  return res.json()
}

export const api = {
  // Feed
  getFeed: (limit = 20) => get(`/api/v2/feed?limit=${limit}`),

  // Opportunity detail + AI
  getOpportunity: (id) => get(`/api/v2/opportunities/${id}`),
  generateSummary: (id) => post(`/api/v2/opportunities/${id}/summary`),
  getAnalysis: (id) => post(`/api/v2/opportunities/${id}/analysis`),

  // Company profile
  getProfile: () => get('/api/v2/company/profile'),

  // Health
  health: () => get('/api/v2/health'),
}

// Supabase direct writes (no Flask needed for simple CRUD)
export const db = {
  // Record a swipe
  recordSwipe: async ({ userId, companyId, opportunityId, direction, dwellMs, expanded, samLinkClicked }) => {
    return supabase.from('swipes').upsert({
      user_id: userId,
      company_id: companyId,
      opportunity_id: opportunityId,
      direction,
      dwell_ms: dwellMs,
      expanded,
      sam_link_clicked: samLinkClicked || false,
    }, { onConflict: 'user_id,opportunity_id' })
  },

  // Add to pipeline
  addToPipeline: async ({ companyId, opportunityId, userId }) => {
    return supabase.from('pipeline').upsert({
      company_id: companyId,
      opportunity_id: opportunityId,
      created_by: userId,
      stage: 'watching',
    }, { onConflict: 'company_id,opportunity_id' })
  },

  // Update pipeline stage
  updatePipelineStage: async (pipelineId, stage) => {
    return supabase.from('pipeline').update({ stage }).eq('id', pipelineId)
  },

  // Count actual left/right swipes today (excludes detail-view expands)
  getTodaySwipeCount: async (userId) => {
    const todayStart = new Date()
    todayStart.setHours(0, 0, 0, 0)
    const { count } = await supabase
      .from('swipes')
      .select('id', { count: 'exact', head: true })
      .eq('user_id', userId)
      .in('direction', ['left', 'right'])
      .gte('created_at', todayStart.toISOString())
    return count || 0
  },

  // Record that a user opened the detail view.
  // Note: swipes table direction column only allows 'left'/'right' — detail views
  // are tracked via the `expanded` flag on the actual swipe record when it's created.
  recordDetailView: async ({ userId, companyId, opportunityId }) => {
    // No-op until a separate detail_views table is added to the schema
    return Promise.resolve()
  },

  // Delete a swipe record (used by undo)
  deleteSwipe: async ({ userId, opportunityId }) => {
    return supabase.from('swipes')
      .delete()
      .eq('user_id', userId)
      .eq('opportunity_id', opportunityId)
  },

  // Remove an opportunity from the pipeline (used by undo when undoing a right-swipe)
  removeFromPipeline: async ({ companyId, opportunityId }) => {
    return supabase.from('pipeline')
      .delete()
      .eq('company_id', companyId)
      .eq('opportunity_id', opportunityId)
  },

  // Bookmark an opportunity — distinct signal from pipeline save
  addBookmark: async ({ companyId, opportunityId, userId }) => {
    return supabase.from('bookmarks').upsert({
      company_id: companyId,
      opportunity_id: opportunityId,
      user_id: userId,
    }, { onConflict: 'company_id,opportunity_id' })
  },

  // Get pipeline for company
  getPipeline: async (companyId) => {
    return supabase.from('pipeline')
      .select('*, opportunities(id,notice_id,title,agency,sub_agency,naics_code,set_aside_type,response_deadline,value_max,ai_summary)')
      .eq('company_id', companyId)
      .order('created_at', { ascending: false })
  },

  // Get bookmarks for company
  getBookmarks: async (companyId) => {
    return supabase.from('bookmarks')
      .select('*, opportunities(id,notice_id,title,agency,sub_agency,naics_code,set_aside_type,response_deadline,value_max,ai_summary)')
      .eq('company_id', companyId)
      .order('created_at', { ascending: false })
  },

  // Remove a bookmark
  removeBookmark: async ({ companyId, opportunityId }) => {
    return supabase.from('bookmarks')
      .delete()
      .eq('company_id', companyId)
      .eq('opportunity_id', opportunityId)
  },

  // Save company profile
  saveCompany: async (companyId, data) => {
    return supabase.from('companies').update(data).eq('id', companyId)
  },

  // Save NAICS codes
  saveNaics: async (companyId, codes) => {
    await supabase.from('company_naics').delete().eq('company_id', companyId)
    if (!codes.length) return
    return supabase.from('company_naics').insert(
      codes.map((c, i) => ({ company_id: companyId, naics_code: c.code, description: c.description, is_primary: i === 0 }))
    )
  },

  // Save keywords
  saveKeywords: async (companyId, keywords) => {
    await supabase.from('company_keywords').delete().eq('company_id', companyId)
    if (!keywords.length) return
    return supabase.from('company_keywords').insert(
      keywords.map(k => ({ company_id: companyId, keyword: k.keyword, is_exclusion: k.is_exclusion || false }))
    )
  },
}
