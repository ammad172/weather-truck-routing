import { useState } from 'react'
import { INTERVALS, type Interval, type PlanRequest } from '../api/types'
import { localInputToIso, localZoneName, nextHour, toLocalInputValue } from '../lib/time'
import { PlaceInput, type PlaceValue } from './PlaceInput'

type Props = {
  onSubmit: (request: PlanRequest) => void
  pending: boolean
  /** Once a plan exists, changing the interval re-plans straight away (it's cached, so fast). */
  hasPlan: boolean
}

const MAX_DAYS_AHEAD = 13 // matches the API's limit (forecast range)
const EMPTY_PLACE: PlaceValue = { text: '', place: null }

export function TripForm({ onSubmit, pending, hasPlan }: Props) {
  const [origin, setOrigin] = useState<PlaceValue>(EMPTY_PLACE)
  const [destination, setDestination] = useState<PlaceValue>(EMPTY_PLACE)
  const [departure, setDeparture] = useState(() => toLocalInputValue(nextHour()))
  const [weight, setWeight] = useState('42000')
  const [intervalMi, setIntervalMi] = useState<Interval>(25)

  const request = (interval: Interval): PlanRequest => ({
    origin: origin.place ?? origin.text.trim(),
    destination: destination.place ?? destination.text.trim(),
    departure: localInputToIso(departure),
    weight_lb: Number(weight),
    interval_mi: interval,
  })

  // Input limits, fixed when the form mounts (the API re-checks on submit).
  const [limits] = useState(() => {
    const now = new Date()
    return { min: toLocalInputValue(now), max: toLocalInputValue(new Date(now.getTime() + MAX_DAYS_AHEAD * 24 * 3600 * 1000)) }
  })

  return (
    <form
      className="trip-form"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit(request(intervalMi))
      }}
    >
      <PlaceInput label="From" value={origin} onChange={setOrigin} placeholder="e.g. Dallas, TX" />
      <PlaceInput label="To" value={destination} onChange={setDestination} placeholder="e.g. Denver, CO" />

      <div className="field-row">
        <div className="field">
          <label htmlFor="departure">Departure</label>
          <input
            id="departure"
            type="datetime-local"
            required
            value={departure}
            min={limits.min}
            max={limits.max}
            onChange={(e) => setDeparture(e.target.value)}
            aria-describedby="departure-zone"
          />
          <span id="departure-zone" className="field-hint">
            Your time ({localZoneName()})
          </span>
        </div>
        <div className="field">
          <label htmlFor="weight">Load weight</label>
          <div className="input-suffix">
            <input
              id="weight"
              type="number"
              inputMode="numeric"
              required
              min={0}
              max={80000}
              step={500}
              value={weight}
              onChange={(e) => setWeight(e.target.value)}
              aria-describedby="weight-hint"
            />
            <span aria-hidden="true">lb</span>
          </div>
          <span id="weight-hint" className="field-hint">
            Cargo only. Above 30,000 / 40,000 lb, strong wind is riskier.
          </span>
        </div>
      </div>

      <fieldset className="field segmented">
        <legend>Weather checkpoint every</legend>
        <div className="segmented-options">
          {INTERVALS.map((value) => (
            <label key={value} className={value === intervalMi ? 'selected' : undefined}>
              <input
                type="radio"
                name="interval"
                value={value}
                checked={value === intervalMi}
                onChange={() => {
                  setIntervalMi(value)
                  if (hasPlan && !pending && origin.text && destination.text) onSubmit(request(value))
                }}
              />
              {value} mi
            </label>
          ))}
        </div>
      </fieldset>

      <button type="submit" className="primary" disabled={pending}>
        {pending ? 'Planning…' : hasPlan ? 'Re-plan routes' : 'Plan routes'}
      </button>
    </form>
  )
}
