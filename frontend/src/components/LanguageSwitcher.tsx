import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { LANGUAGES, useI18n } from '../i18n'
import { CheckIcon, GlobeIcon } from './icons'

/** Sidebar-footer language menu; switches the UI language immediately. */
export function LanguageSwitcher() {
  const { language, t, setLanguage } = useI18n()
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const menuId = useId()

  useEffect(() => {
    if (!open) return
    const onPointer = (event: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onPointer)
    wrapRef.current?.querySelector<HTMLElement>('[aria-checked="true"]')?.focus()
    return () => document.removeEventListener('mousedown', onPointer)
  }, [open])

  const close = () => {
    setOpen(false)
    buttonRef.current?.focus()
  }

  const onMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitemradio"]'))
    const index = items.indexOf(document.activeElement as HTMLElement)
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const step = event.key === 'ArrowDown' ? 1 : -1
      items[(index + step + items.length) % items.length]?.focus()
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      items[event.key === 'Home' ? 0 : items.length - 1]?.focus()
    } else if (event.key === 'Tab') {
      setOpen(false)
    }
  }

  const choose = (code: string) => {
    close()
    if (code !== language.code) void setLanguage(code)
  }

  return (
    <div className="language-switcher" ref={wrapRef}>
      <button
        ref={buttonRef}
        type="button"
        className="language-switcher-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={t('language.current', { name: language.nativeName })}
        title={t('language.label')}
        onClick={() => setOpen((value) => !value)}
      >
        <GlobeIcon size={16} />
        <span className="language-native" lang={language.locale}>
          {language.nativeName}
        </span>
      </button>
      {open && (
        <div id={menuId} className="language-menu" role="menu" aria-label={t('language.options')} onKeyDown={onMenuKeyDown}>
          {LANGUAGES.map((option) => {
            const checked = option.code === language.code
            return (
              <button
                key={option.code}
                type="button"
                role="menuitemradio"
                aria-checked={checked}
                tabIndex={checked ? 0 : -1}
                className={`language-menu-item${checked ? ' selected' : ''}`}
                onClick={() => choose(option.code)}
              >
                <span className="language-native" lang={option.locale}>
                  {option.nativeName}
                </span>
                <span className="language-menu-english">{option.englishName}</span>
                {checked && <CheckIcon size={15} className="language-menu-check" />}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
