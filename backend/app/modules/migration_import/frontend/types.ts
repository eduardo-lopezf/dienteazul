/**
 * Shared types for the data-migration frontend layer.
 *
 * Mirrors `ImportJobResponse` in
 * ``backend/app/modules/migration_import/schemas.py``, which answers both
 * `/jobs` and `/sheets`. It lives here because two components pass a job
 * between them: declaring it twice made the wizard's handler and the sheet
 * step's `ready` event two unrelated types, and the typecheck gate caught
 * exactly that.
 */

/** Every value the job table accepts (`ck_migration_import_job_status`). */
export type JobStatus
  = | 'mapping'
    | 'uploaded'
    | 'validating'
    | 'validated'
    | 'previewing'
    | 'executing'
    | 'completed'
    | 'failed'

export interface ImportJob {
  id: string
  status: JobStatus
  error: string | null
  original_filename: string
  file_size: number
  source_system: string | null
  format_version: string | null
  tenant_label: string | null
  total_entities: number
  processed_entities: number
}
