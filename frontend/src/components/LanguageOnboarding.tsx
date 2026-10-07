import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { createTranslator, getLanguage, LANGUAGES, loadMessages, useI18n } from '../i18n'
import type { PartialMessages } from '../i18n/messages/en'
import { ArrowRightIcon, AtlasMark, CheckCircleIcon } from './icons'

/**
 * First-launch language choice. The dialog previews its own text in the
 * highlighted language; nothing is stored until Continue.
 */
export function LanguageOnboarding() {
  const { suggestedLanguage, completeOnboarding } = useI18n()
  const [selected, setSelected] = useState(suggestedLanguage)
  const [preview, setPreview] = useState<{ code: string; messages: PartialMessages } | null>(null)
  const [busy, setBusy] = useState(false)
  const titleId = useId()
  const hintId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    void loadMessages(selected).then((messages) => {
      if (!cancelled) setPreview({ code: selected, messages })
    })
    return () => {
      cancelled = true
    }
  }, [selected])

  useEffect(() => {
    dialogRef.current?.querySelector<HTMLInputElement>('input:checked')?.focus()
  }, [])

  const t = useMemo(
    () => (preview ? createTranslator(preview.code, preview.messages) : createTranslator('en', {})),
    [preview],
  )
  const previewLocale = getLanguage(preview?.code).locale

  const handleContinue = async () => {
    setBusy(true)
    await completeOnboarding(selected)
  }

  return (
    <div className="language-onboarding" role="presentation">
      <div
        ref={dialogRef}
        className="language-onboarding-card glass-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={hintId}
        lang={previewLocale}
      >
        <AtlasMark size={36} className="language-onboarding-mark" />
        <h1 id={titleId} className="language-onboarding-title">
          {t('onboarding.welcome')}
        </h1>
        <p className="language-onboarding-subtitle">{t('onboarding.choose')}</p>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            void handleContinue()
          }}
        >
          <fieldset className="language-options">
            <legend className="visually-hidden">{t('onboarding.choose')}</legend>
            {LANGUAGES.map((language) => {
              const checked = selected === language.code
              return (
                <label key={language.code} className={`language-option${checked ? ' selected' : ''}`}>
                  <input
                    type="radio"
                    name="atlas-language"
                    value={language.code}
                    checked={checked}
                    onChange={() => setSelected(language.code)}
                    className="visually-hidden"
                  />
                  <span className="language-option-native language-native" lang={language.locale}>
                    {language.nativeName}
                  </span>
                  <span className="language-option-english">{language.englishName}</span>
                  {checked && <CheckCircleIcon size={18} className="language-option-check" />}
                </label>
              )
            })}
          </fieldset>
          <p id={hintId} className="language-onboarding-hint">
            {t('onboarding.hint')}
          </p>
          <button type="submit" className="btn primary glow large language-onboarding-continue" disabled={busy}>
            <span>{t('onboarding.continue')}</span>
            <ArrowRightIcon size={16} />
          </button>
        </form>
      </div>
    </div>
  )
}
