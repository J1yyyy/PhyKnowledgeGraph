const STORAGE_KEY = 'junior-physics-question-session'

export const loadQuestionSession = () => {
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null')
    if (!saved || typeof saved.question !== 'string' || !saved.result) return saved?.question ? saved : null
    if (saved.result.project_id !== 'junior_physics' || !Array.isArray(saved.result.candidates)
      || !saved.result.candidates.length || saved.result.candidates.length > 5 || !saved.result.analysis) return null
    return saved
  } catch {
    return null
  }
}

export const saveQuestionSession = state => {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state))
    return true
  } catch {
    return false
  }
}
