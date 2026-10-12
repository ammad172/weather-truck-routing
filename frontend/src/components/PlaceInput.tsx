import { useQuery } from '@tanstack/react-query'
import { type KeyboardEvent, useEffect, useId, useState } from 'react'
import { geocode } from '../api/client'
import type { Place } from '../api/types'

/** What the user typed, and the suggestion they picked (if any). */
export type PlaceValue = { text: string; place: Place | null }

type Props = {
  label: string
  value: PlaceValue
  onChange: (value: PlaceValue) => void
  placeholder?: string
}

const DEBOUNCE_MS = 250

/** Text input with place suggestions (ARIA combobox pattern). */
export function PlaceInput({ label, value, onChange, placeholder }: Props) {
  const id = useId()
  const listId = `${id}-list`
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const query = useDebounced(value.text.trim(), DEBOUNCE_MS)

  const suggestions = useQuery({
    queryKey: ['geocode', query],
    queryFn: ({ signal }) => geocode(query, signal),
    enabled: open && !value.place && query.length >= 2,
    staleTime: 24 * 60 * 60 * 1000,
  })
  const options = open && !value.place ? (suggestions.data ?? []) : []

  const pick = (place: Place) => {
    onChange({ text: place.label, place })
    setOpen(false)
    setActive(-1)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' && options.length) {
      event.preventDefault()
      setOpen(true)
      setActive((i) => (i + 1) % options.length)
    } else if (event.key === 'ArrowUp' && options.length) {
      event.preventDefault()
      setActive((i) => (i <= 0 ? options.length - 1 : i - 1))
    } else if (event.key === 'Enter' && active >= 0 && options[active]) {
      event.preventDefault()
      pick(options[active])
    } else if (event.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div className="field place-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="text"
        role="combobox"
        autoComplete="off"
        aria-autocomplete="list"
        aria-expanded={options.length > 0}
        aria-controls={listId}
        aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
        placeholder={placeholder}
        value={value.text}
        required
        onChange={(e) => {
          onChange({ text: e.target.value, place: null })
          setOpen(true)
          setActive(-1)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
      />
      {value.place && <span className="field-check" aria-hidden="true">✓</span>}
      {options.length > 0 && (
        <ul id={listId} role="listbox" className="suggestions">
          {options.map((place, i) => (
            <li
              key={`${place.lat},${place.lon}`}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? 'active' : undefined}
              // mousedown, not click: it fires before the input's blur closes the list.
              onMouseDown={(e) => {
                e.preventDefault()
                pick(place)
              }}
            >
              {place.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return debounced
}
