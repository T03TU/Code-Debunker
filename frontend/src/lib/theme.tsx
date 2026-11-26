import {
  createContext,
  useContext,
  useLayoutEffect,
  useState,
  type ReactNode,
} from "react";

export const accents = {
  violet: { label: "Violet", dark: "#b8a1f2", light: "#6d42bd" },
  blue: { label: "Blue", dark: "#8dbbff", light: "#245fbd" },
  teal: { label: "Teal", dark: "#77d7c3", light: "#087b6b" },
  rose: { label: "Rose", dark: "#f4a4bd", light: "#b52d5c" },
  amber: { label: "Amber", dark: "#e9c17b", light: "#916009" },
};
export const fonts = {
  sans: {
    label: "Sans serif",
    value: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  },
  system: { label: "System", value: "system-ui, sans-serif" },
  mono: { label: "Monospace", value: '"JetBrains Mono", Consolas, monospace' },
};
export const textSizes = { small: 14, medium: 16, large: 18 };
export const iconWeights = { fine: 1.5, regular: 2, bold: 2.75 };
export interface ThemePreferences {
  mode: "dark" | "light" | "system";
  accent: keyof typeof accents;
  font: keyof typeof fonts;
  textSize: keyof typeof textSizes;
  icons: keyof typeof iconWeights;
}
export const defaultTheme: ThemePreferences = {
  mode: "dark",
  accent: "violet",
  font: "sans",
  textSize: "medium",
  icons: "regular",
};
const storageKey = "codedebunker.appearance.v1";

function parsePreferences(raw: string | null): ThemePreferences {
  try {
    const value = JSON.parse(raw ?? "null");
    if (!value || typeof value !== "object") return defaultTheme;
    return {
      mode: ["dark", "light", "system"].includes(value.mode)
        ? value.mode
        : defaultTheme.mode,
      accent: Object.hasOwnProperty.call(accents, value.accent)
        ? value.accent
        : defaultTheme.accent,
      font: Object.hasOwnProperty.call(fonts, value.font)
        ? value.font
        : defaultTheme.font,
      textSize: Object.hasOwnProperty.call(textSizes, value.textSize)
        ? value.textSize
        : defaultTheme.textSize,
      icons: Object.hasOwnProperty.call(iconWeights, value.icons)
        ? value.icons
        : defaultTheme.icons,
    };
  } catch {
    return defaultTheme;
  }
}

const ThemeContext = createContext<{
  preferences: ThemePreferences;
  resolvedMode: "dark" | "light";
  updateTheme: (patch: Partial<ThemePreferences>) => void;
  resetTheme: () => void;
  storageError: boolean;
} | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preferences, setPreferences] = useState(() => {
    try {
      return parsePreferences(localStorage.getItem(storageKey));
    } catch {
      return defaultTheme;
    }
  });
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia("(prefers-color-scheme: dark)").matches,
  );
  const [storageError, setStorageError] = useState(false);
  const resolvedMode =
    preferences.mode === "system"
      ? systemDark
        ? "dark"
        : "light"
      : preferences.mode;

  useLayoutEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const changed = () => setSystemDark(media.matches);
    media.addEventListener("change", changed);
    const storageChanged = (event: StorageEvent) => {
      if (event.key === storageKey || event.key === null)
        setPreferences(parsePreferences(event.newValue));
    };
    window.addEventListener("storage", storageChanged);
    return () => {
      media.removeEventListener("change", changed);
      window.removeEventListener("storage", storageChanged);
    };
  }, []);

  useLayoutEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = resolvedMode;
    root.style.colorScheme = resolvedMode;
    root.style.setProperty(
      "--accent",
      accents[preferences.accent][resolvedMode],
    );
    root.style.setProperty("--font-ui", fonts[preferences.font].value);
    root.style.setProperty(
      "--font-size",
      `${textSizes[preferences.textSize]}px`,
    );
    root.style.setProperty(
      "--icon-weight",
      String(iconWeights[preferences.icons]),
    );
  }, [preferences, resolvedMode]);

  function updateTheme(patch: Partial<ThemePreferences>) {
    const next = { ...preferences, ...patch };
    setPreferences(next);
    try {
      localStorage.setItem(storageKey, JSON.stringify(next));
      setStorageError(false);
    } catch {
      setStorageError(true);
    }
  }
  return (
    <ThemeContext.Provider
      value={{
        preferences,
        resolvedMode,
        updateTheme,
        resetTheme: () => updateTheme(defaultTheme),
        storageError,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme requires ThemeProvider");
  return context;
}
