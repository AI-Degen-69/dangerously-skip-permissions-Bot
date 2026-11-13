import { useCallback, useEffect, useState } from 'react'

/**
 * A boolean that survives a reload and is shared with every other tab, so two
 * views of the same number never answer differently.
 */
export function useStoredFlag(key: string, fallback: boolean): [boolean, (value: boolean) => void] {
  const storageKey = `dsp.${key}`
  const eventName = `dsp:flag-${key}`

  const read = useCallback(() => {
    try {
      const raw = window.localStorage.getItem(storageKey)
      return raw === null ? fallback : raw === 'true'
    } catch {
      return fallback
    }
  }, [storageKey, fallback])

  const [value, setValue] = useState<boolean>(() =>
    typeof window === 'undefined' ? fallback : read(),
  )

  useEffect(() => {
    const sync = () => setValue(read())
    const onPick = (event: Event) => setValue((event as CustomEvent<boolean>).detail)
    window.addEventListener('storage', sync)
    window.addEventListener(eventName, onPick)
    return () => {
      window.removeEventListener('storage', sync)
      window.removeEventListener(eventName, onPick)
    }
  }, [read, eventName])

  const pick = useCallback((next: boolean) => {
    setValue(next)
    try {
      window.localStorage.setItem(storageKey, String(next))
    } catch {
      // Private-mode storage failures must not block the switch.
    }
    window.dispatchEvent(new CustomEvent(eventName, { detail: next }))
  }, [storageKey, eventName])

  return [value, pick]
}
