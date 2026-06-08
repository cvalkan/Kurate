import { createContext, useContext } from "react";

const BasePath = createContext("");

export function BasePathProvider({ value, children }) {
  return <BasePath.Provider value={value}>{children}</BasePath.Provider>;
}

/** Returns "" for the current production site, "/new" for the new design preview. */
export function useBasePath() {
  return useContext(BasePath);
}
