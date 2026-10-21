import { describe, expect, it } from 'vitest'
import {
  PEDIATRIC_QUESTION_GROUPS,
  PEDIATRIC_QUESTIONS,
  QUESTIONS,
  questionsOf,
  suggestedForm
} from '../../backend/app/modules/patients_clinical/frontend/composables/useHealthQuestionnaires'
import es from '../i18n/locales/es.json'
import en from '../i18n/locales/en.json'

describe('which health questionnaire is offered', () => {
  const today = new Date(2026, 9, 21)

  it('offers the pediatric form under 18 and the adult one from 18', () => {
    expect(suggestedForm('2016-03-15', today)).toBe('pediatric')
    expect(suggestedForm('2008-10-22', today)).toBe('pediatric') // 18 tomorrow
    expect(suggestedForm('2008-10-21', today)).toBe('adult') // 18 today
    expect(suggestedForm(null, today)).toBe('adult')
  })

  it('reads each questionnaire back with its own questions', () => {
    expect(questionsOf('adult')).toBe(QUESTIONS)
    expect(questionsOf('pediatric')).toEqual(Object.values(PEDIATRIC_QUESTION_GROUPS).flat())
    expect(questionsOf(undefined)).toBe(QUESTIONS)
  })

  it('has words for every pediatric question in both languages', () => {
    for (const locale of [es, en]) {
      const questions = (locale as { healthQuestionnaire: { questions: Record<string, string> } }).healthQuestionnaire.questions
      for (const key of PEDIATRIC_QUESTIONS) expect(questions[key], key).toBeTruthy()
    }
  })
})
