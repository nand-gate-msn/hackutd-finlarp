import { createContext, useContext } from 'react'
export const PresenceState = createContext(true)
export const usePresenceState = () => useContext(PresenceState)
