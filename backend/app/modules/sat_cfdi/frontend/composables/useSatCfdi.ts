import type { ApiResponse } from '~~/app/types'

/** The clinic's CSD as the API shows it: never its key or password. */
export interface SatCertificate {
  id: string
  certificate_number: string
  rfc: string
  valid_from: string
  valid_until: string
  is_active: boolean
  created_at: string
  /** Where Facturama holds it, to seal with. */
  registered_in: SatEnvironment[]
  /** Why the last attempt to register it did not go through. */
  registration_error: string | null
}

export type SatEnvironment = 'sandbox' | 'production'

/** The clinic's own Facturama account in one environment: never the password. */
export interface FacturamaAccount {
  user: string | null
  has_password: boolean
}

export interface SatSettings {
  /** The clinic's own tax ID and legal name, edited in Clinic info. */
  rfc: string | null
  legal_name: string | null
  tax_regime: string | null
  expedition_postal_code: string | null
  environment: SatEnvironment
  /** `c_ClaveProdServ` of every line; no default. */
  product_code: string | null
  /** `c_ClaveUnidad`; `E48` by default. */
  unit_code: string
  stamp_delay_minutes: number
  facturama: Record<SatEnvironment, FacturamaAccount>
  certificate: SatCertificate | null
  ready: boolean
  /** Why the clinic cannot issue yet; null when it can. */
  missing: string | null
}

export interface SatSettingsDraft {
  tax_regime: string
  expedition_postal_code: string
  environment: SatEnvironment
  product_code: string | null
  unit_code: string
  stamp_delay_minutes: number
}

/** A receiver's fiscal profile, kept by RFC. */
export interface SatReceiver {
  rfc: string
  tax_regime: string
  tax_zip_code: string
  cfdi_use: string
  updated_at: string
}

export interface SatReceiverDraft {
  tax_regime: string
  tax_zip_code: string
  cfdi_use: string
}

/** The SAT's generic RFC for the general public: needs no profile. */
export const PUBLIC_RFC = 'XAXX010101000'

/** `c_UsoCFDI`, with the SAT's own names. */
export const CFDI_USES: { value: string, label: string }[] = [
  { value: 'D01', label: 'Honorarios médicos, dentales y gastos hospitalarios' },
  { value: 'D02', label: 'Gastos médicos por incapacidad o discapacidad' },
  { value: 'D03', label: 'Gastos funerales' },
  { value: 'D04', label: 'Donativos' },
  { value: 'D05', label: 'Intereses reales efectivamente pagados por créditos hipotecarios (casa habitación)' },
  { value: 'D06', label: 'Aportaciones voluntarias al SAR' },
  { value: 'D07', label: 'Primas por seguros de gastos médicos' },
  { value: 'D08', label: 'Gastos de transportación escolar obligatoria' },
  { value: 'D09', label: 'Depósitos en cuentas para el ahorro, primas que tengan como base planes de pensiones' },
  { value: 'D10', label: 'Pagos por servicios educativos (colegiaturas)' },
  { value: 'G01', label: 'Adquisición de mercancías' },
  { value: 'G02', label: 'Devoluciones, descuentos o bonificaciones' },
  { value: 'G03', label: 'Gastos en general' },
  { value: 'I01', label: 'Construcciones' },
  { value: 'I02', label: 'Mobiliario y equipo de oficina por inversiones' },
  { value: 'I03', label: 'Equipo de transporte' },
  { value: 'I04', label: 'Equipo de cómputo y accesorios' },
  { value: 'I05', label: 'Dados, troqueles, moldes, matrices y herramental' },
  { value: 'I06', label: 'Comunicaciones telefónicas' },
  { value: 'I07', label: 'Comunicaciones satelitales' },
  { value: 'I08', label: 'Otra maquinaria y equipo' },
  { value: 'S01', label: 'Sin efectos fiscales' },
  { value: 'CP01', label: 'Pagos' },
  { value: 'CN01', label: 'Nómina' }
]

/** `c_RegimenFiscal`, with the SAT's own names. */
export const TAX_REGIMES: { value: string, label: string }[] = [
  { value: '601', label: 'General de Ley Personas Morales' },
  { value: '603', label: 'Personas Morales con Fines no Lucrativos' },
  { value: '605', label: 'Sueldos y Salarios e Ingresos Asimilados a Salarios' },
  { value: '606', label: 'Arrendamiento' },
  { value: '607', label: 'Régimen de Enajenación o Adquisición de Bienes' },
  { value: '608', label: 'Demás ingresos' },
  { value: '610', label: 'Residentes en el Extranjero sin Establecimiento Permanente en México' },
  { value: '611', label: 'Ingresos por Dividendos (socios y accionistas)' },
  { value: '612', label: 'Personas Físicas con Actividades Empresariales y Profesionales' },
  { value: '614', label: 'Ingresos por intereses' },
  { value: '615', label: 'Régimen de los ingresos por obtención de premios' },
  { value: '616', label: 'Sin obligaciones fiscales' },
  { value: '620', label: 'Sociedades Cooperativas de Producción que optan por diferir sus ingresos' },
  { value: '621', label: 'Incorporación Fiscal' },
  { value: '622', label: 'Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras' },
  { value: '623', label: 'Opcional para Grupos de Sociedades' },
  { value: '624', label: 'Coordinados' },
  { value: '625', label: 'Régimen de las Actividades Empresariales con ingresos a través de Plataformas Tecnológicas' },
  { value: '626', label: 'Régimen Simplificado de Confianza' }
]

export function useSatCfdi() {
  const api = useApi()
  const base = '/api/v1/sat_cfdi'

  async function getSettings(): Promise<SatSettings> {
    return (await api.get<ApiResponse<SatSettings>>(`${base}/settings`)).data
  }

  async function saveSettings(draft: SatSettingsDraft): Promise<SatSettings> {
    return (await api.put<ApiResponse<SatSettings>>(`${base}/settings`, draft)).data
  }

  async function uploadCertificate(cer: File, key: File, password: string): Promise<SatCertificate> {
    const form = new FormData()
    form.append('cer', cer)
    form.append('key', key)
    form.append('password', password)
    return (await api.post<ApiResponse<SatCertificate>>(`${base}/certificate`, form)).data
  }

  /** The clinic's Facturama account for an environment; no password keeps the stored one. */
  async function saveCredentials(environment: SatEnvironment, user: string, password: string | null): Promise<SatSettings> {
    const body: Record<string, string> = { environment, user }
    if (password) body.password = password
    return (await api.put<ApiResponse<SatSettings>>(`${base}/facturama-credentials`, body)).data
  }

  async function registerCertificate(): Promise<SatCertificate> {
    return (await api.post<ApiResponse<SatCertificate>>(`${base}/certificate/register`, {})).data
  }

  /** The profile kept for an RFC, or null when there is none yet. */
  async function getReceiver(rfc: string): Promise<SatReceiver | null> {
    return (await api.get<ApiResponse<SatReceiver | null>>(`${base}/receivers/${encodeURIComponent(rfc)}`)).data
  }

  async function saveReceiver(rfc: string, draft: SatReceiverDraft): Promise<SatReceiver> {
    return (await api.put<ApiResponse<SatReceiver>>(`${base}/receivers/${encodeURIComponent(rfc)}`, draft)).data
  }

  return { getSettings, saveSettings, saveCredentials, uploadCertificate, registerCertificate, getReceiver, saveReceiver }
}
