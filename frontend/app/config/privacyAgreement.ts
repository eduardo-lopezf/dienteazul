/**
 * The version of the privacy agreement shown in the welcome
 * (`onboarding.privacy.sections` in the locale files). It is sent when
 * the holder accepts and kept with the acceptance, so the record says
 * which text was on the screen.
 *
 * Change it whenever the agreement's text changes, in any language: the
 * date of the change, and a letter after it for a second one that day.
 * **Change it in `backend/app/core/auth/privacy_agreement.py` too** — the
 * backend refuses an acceptance of any other version, and asks every
 * clinic that accepted an earlier one to accept again
 * (`tests/privacy-agreement.test.ts` fails when the two differ).
 */
export const PRIVACY_AGREEMENT_VERSION = '2026-10-12'
