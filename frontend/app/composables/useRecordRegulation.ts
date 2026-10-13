import type { ApiResponse } from '~/types'

/**
 * The regulation the clinic's clinical record refers to: one line of text
 * the clinic sets, printed on the health questionnaire and on the record.
 * Read once per session and shared — several screens show it.
 */
export interface RecordRegulation {
  /** The line that is shown; null when the clinic shows none. */
  text: string | null
  /** What the product offers for the clinic's country, if it knows one. */
  default: string | null
  /** True while the clinic has not written its own. */
  is_default: boolean
}

const URL = '/api/v1/auth/clinic/settings/record-regulation'

export function useRecordRegulation() {
  const api = useApi()
  const regulation = useState<RecordRegulation | null>('recordRegulation', () => null)

  async function load(force = false): Promise<RecordRegulation | null> {
    if (regulation.value && !force) return regulation.value
    try {
      regulation.value = (await api.get<ApiResponse<RecordRegulation>>(URL)).data
    } catch {
      // Not worth an error on a form: the line is simply not shown.
      regulation.value = null
    }
    return regulation.value
  }

  /** `null` goes back to the suggested one; an empty string shows none. */
  async function save(text: string | null): Promise<RecordRegulation> {
    regulation.value = (await api.put<ApiResponse<RecordRegulation>>(URL, { text })).data
    return regulation.value
  }

  return { regulation, load, save }
}
