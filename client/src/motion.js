// Shared, interruptible rAF spring. Positions are pixels (or unitless); velocities are units/second.
export const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

export function createSpring(initial, update, { damping = 1, response = .4 } = {}) {
  let value = { ...initial }, target = { ...initial }
  let velocity = Object.fromEntries(Object.keys(initial).map(key => [key, 0]))
  let frame = 0, last = 0
  const preference = window.matchMedia('(prefers-reduced-motion: reduce)')
  const stop = () => { cancelAnimationFrame(frame); frame = 0; last = 0 }
  const set = next => {
    stop(); value = { ...next }; target = { ...next }
    velocity = Object.fromEntries(Object.keys(next).map(key => [key, 0]))
    update({ ...value })
  }
  const tick = now => {
    const dt = Math.min((now - (last || now - 16)) / 1000, .064)
    last = now
    const w = 2 * Math.PI / response
    let done = true
    for (const key of Object.keys(value)) {
      const x = value[key] - target[key], v = velocity[key]
      if (damping === 1) {
        const b = v + w * x, decay = Math.exp(-w * dt)
        value[key] = target[key] + (x + b * dt) * decay
        velocity[key] = (v - w * b * dt) * decay
      } else {
        const wd = w * Math.sqrt(1 - damping * damping), decay = Math.exp(-damping * w * dt)
        const b = (v + damping * w * x) / wd, c = Math.cos(wd * dt), s = Math.sin(wd * dt)
        value[key] = target[key] + decay * (x * c + b * s)
        velocity[key] = decay * ((b * wd - damping * w * x) * c - (x * wd + damping * w * b) * s)
      }
      const tolerance = key === 'k' ? .0001 : .05
      if (Math.abs(value[key] - target[key]) > tolerance || Math.abs(velocity[key]) > tolerance) done = false
    }
    if (preference.matches || done) { set(target); return }
    update({ ...value })
    frame = requestAnimationFrame(tick)
  }
  const onPreference = () => { if (preference.matches) set(target) }
  preference.addEventListener('change', onPreference)
  return {
    get value() { return { ...value } },
    get velocity() { return { ...velocity } },
    set, stop,
    to(next, handoff) {
      target = { ...next }
      if (handoff) velocity = { ...velocity, ...handoff }
      if (preference.matches) { set(target); return }
      if (!frame) { last = 0; frame = requestAnimationFrame(tick) }
    },
    destroy() { stop(); preference.removeEventListener('change', onPreference) },
  }
}
