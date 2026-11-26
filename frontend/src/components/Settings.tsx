import { useEffect, useRef, useState } from "react";
import {
  Braces,
  Check,
  Monitor,
  Moon,
  Palette,
  Settings2,
  Sparkles,
  Sun,
  X,
} from "lucide-react";
import LLMSettingsForm from "@/components/LLMSettingsForm";
import { accents, fonts, useTheme, type ThemePreferences } from "@/lib/theme";

interface Props {
  onClose: () => void;
  onLLMSaved: () => void;
  initialSection?: "appearance" | "llm";
}

export default function Settings({
  onClose,
  onLLMSaved,
  initialSection = "appearance",
}: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const { preferences, resolvedMode, updateTheme, resetTheme, storageError } =
    useTheme();
  const [section, setSection] = useState<"appearance" | "llm">(initialSection);
  const [llmBusy, setLLMBusy] = useState(false);

  useEffect(() => {
    const element = dialog.current!;
    const previousFocus = document.activeElement;
    element.showModal();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      element.close();
      document.body.style.overflow = overflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected)
        previousFocus.focus();
    };
  }, []);

  return (
    <dialog
      ref={dialog}
      className="settings-dialog"
      aria-labelledby="settings-title"
      onCancel={(event) => {
        if (llmBusy) event.preventDefault();
        else onClose();
      }}
      onClick={(event) => {
        if (!llmBusy && event.target === event.currentTarget) onClose();
      }}
    >
      <div className="settings-surface">
        <header className="settings-header">
          <div>
            <p className="eyebrow">YOUR WORKSPACE</p>
            <h2 id="settings-title">Settings</h2>
          </div>
          <button
            autoFocus
            className="icon-button"
            aria-label="Close settings"
            disabled={llmBusy}
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </header>
        <nav className="settings-nav" aria-label="Settings sections">
          <button
            disabled={llmBusy}
            aria-pressed={section === "appearance"}
            onClick={() => setSection("appearance")}
          >
            <Palette size={17} />
            Appearance
          </button>
          <button
            disabled={llmBusy}
            aria-pressed={section === "llm"}
            onClick={() => setSection("llm")}
          >
            <Settings2 size={17} />
            LLM configuration
          </button>
        </nav>
        <div className="settings-content">
          {section === "appearance" ? (
            <section aria-labelledby="appearance-heading">
              <h3 id="appearance-heading">Make it feel like you</h3>
              <p className="settings-description">
                Changes apply instantly and are saved in this browser.
              </p>
              <fieldset className="settings-field">
                <legend>Color theme</legend>
                <div className="theme-choices">
                  {(
                    [
                      { value: "dark", label: "Dark", Icon: Moon },
                      { value: "light", label: "Light", Icon: Sun },
                      { value: "system", label: "System", Icon: Monitor },
                    ] as const
                  ).map(({ value, label, Icon }) => (
                    <button
                      key={value}
                      className="theme-choice"
                      aria-pressed={preferences.mode === value}
                      onClick={() => updateTheme({ mode: value })}
                    >
                      <Icon size={22} />
                      <span>{label}</span>
                      {preferences.mode === value && (
                        <Check size={14} className="choice-check" />
                      )}
                    </button>
                  ))}
                </div>
              </fieldset>
              <fieldset className="settings-field">
                <legend>Accent color</legend>
                <div className="accent-choices">
                  {Object.entries(accents).map(([key, accent]) => (
                    <button
                      key={key}
                      className="accent-choice"
                      aria-pressed={preferences.accent === key}
                      onClick={() =>
                        updateTheme({
                          accent: key as ThemePreferences["accent"],
                        })
                      }
                    >
                      <span
                        className="accent-swatch"
                        style={{ background: accent[resolvedMode] }}
                      />
                      {accent.label}
                      {preferences.accent === key && <Check size={13} />}
                    </button>
                  ))}
                </div>
              </fieldset>
              <div className="settings-grid">
                <div className="settings-field">
                  <label htmlFor="settings-text-style">Text style</label>
                  <select
                    id="settings-text-style"
                    value={preferences.font}
                    onChange={(event) =>
                      updateTheme({
                        font: event.target.value as ThemePreferences["font"],
                      })
                    }
                  >
                    {Object.entries(fonts).map(([key, font]) => (
                      <option key={key} value={key}>
                        {font.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="settings-field">
                  <label htmlFor="settings-text-size">Text size</label>
                  <select
                    id="settings-text-size"
                    value={preferences.textSize}
                    onChange={(event) =>
                      updateTheme({
                        textSize: event.target
                          .value as ThemePreferences["textSize"],
                      })
                    }
                  >
                    <option value="small">Small</option>
                    <option value="medium">Default</option>
                    <option value="large">Large</option>
                  </select>
                </div>
                <div className="settings-field">
                  <label htmlFor="settings-icon-style">Icon style</label>
                  <select
                    id="settings-icon-style"
                    value={preferences.icons}
                    onChange={(event) =>
                      updateTheme({
                        icons: event.target.value as ThemePreferences["icons"],
                      })
                    }
                  >
                    <option value="fine">Fine</option>
                    <option value="regular">Regular</option>
                    <option value="bold">Bold</option>
                  </select>
                </div>
              </div>
              <div className="theme-preview" aria-label="Theme preview">
                <span className="brand-icon">
                  <Braces size={24} />
                </span>
                <div>
                  <strong>A clearer view of your code.</strong>
                  <p>Your colors, text, and icons in one workspace.</p>
                </div>
                <Sparkles size={22} />
              </div>
              <div className="settings-actions">
                <button className="button secondary" onClick={resetTheme}>
                  Reset appearance
                </button>
                <span role="status" className="settings-description">
                  {storageError
                    ? "Applied for this session. Browser storage is unavailable."
                    : "Saved automatically"}
                </span>
              </div>
            </section>
          ) : (
            <LLMSettingsForm onSaved={onLLMSaved} onBusyChange={setLLMBusy} />
          )}
        </div>
      </div>
    </dialog>
  );
}
