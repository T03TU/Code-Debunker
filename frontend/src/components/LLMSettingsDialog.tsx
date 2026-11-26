import { useEffect, useRef, useState, type FormEvent } from "react";
import { LoaderCircle, Settings2, X } from "lucide-react";
import {
  getLLMSettings,
  saveLLMSettings,
  testLLMConnection,
  type CredentialField,
  type LLMForm,
  type LLMProvider,
  type LLMSettings,
} from "@/lib/api";

const providers: {
  id: LLMProvider;
  name: string;
  endpoint: string;
  hint: string;
}[] = [
  {
    id: "openai",
    name: "OpenAI",
    endpoint: "",
    hint: "Enter a chat model ID from your OpenAI account.",
  },
  {
    id: "anthropic",
    name: "Anthropic / Claude",
    endpoint: "",
    hint: "Enter a Claude model ID from your Anthropic account.",
  },
  {
    id: "gemini",
    name: "Google Gemini",
    endpoint: "",
    hint: "Use a Gemini API key from Google AI Studio and a model ID.",
  },
  {
    id: "azure",
    name: "Microsoft Azure OpenAI",
    endpoint: "",
    hint: "Use your deployment name as the model and your Azure resource endpoint.",
  },
  {
    id: "bedrock",
    name: "Amazon Bedrock",
    endpoint: "",
    hint: "Enter a Bedrock model or inference profile ID. Use an API key, AWS credentials below, or the backend's AWS identity.",
  },
  {
    id: "vertex_ai",
    name: "Google Cloud Vertex AI",
    endpoint: "",
    hint: "Enter a Vertex model ID, project, and location. Paste service account JSON or use the backend's Google Cloud identity.",
  },
  {
    id: "ollama",
    name: "Ollama (local)",
    endpoint: "http://127.0.0.1:11434",
    hint: "Start Ollama and enter an installed model name, including its tag. Use the server root URL, without /v1.",
  },
  {
    id: "lmstudio",
    name: "LM Studio (local)",
    endpoint: "http://127.0.0.1:1234/v1",
    hint: "Load a model and start LM Studio's local server. Enter its model ID.",
  },
  {
    id: "openrouter",
    name: "OpenRouter",
    endpoint: "",
    hint: "Enter the full model ID, including the provider prefix shown by OpenRouter.",
  },
  {
    id: "compatible",
    name: "Other OpenAI-compatible service",
    endpoint: "",
    hint: "Connect vLLM, llama.cpp, a gateway, or another compatible service. Include /v1 in the base URL if required by your server.",
  },
  {
    id: "custom",
    name: "Other provider (LiteLLM)",
    endpoint: "",
    hint: "Enter a LiteLLM provider/model ID, such as mistral/your-model or groq/your-model. Use an optional custom endpoint.",
  },
];

function blankForm(provider: LLMProvider = "openai"): LLMForm {
  return {
    provider,
    model: "",
    base_url: providers.find((item) => item.id === provider)!.endpoint,
    api_key: "",
    output_mode: ["ollama", "lmstudio", "compatible"].includes(provider)
      ? "json"
      : "tools",
    api_version: "",
    aws_region_name: "",
    aws_access_key_id: "",
    aws_secret_access_key: "",
    aws_session_token: "",
    vertex_project: "",
    vertex_location: "",
    vertex_credentials: "",
    clear_credentials: false,
  };
}

export default function LLMSettingsDialog({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [form, setForm] = useState<LLMForm>(blankForm());
  const [saved, setSaved] = useState<LLMSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<"test" | "save" | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const pending = loading || action !== null;
  const preset = providers.find((item) => item.id === form.provider)!;
  const sameService =
    saved &&
    (
      [
        "provider",
        "base_url",
        "api_version",
        "aws_region_name",
        "vertex_project",
        "vertex_location",
      ] as const
    ).every(
      (key) =>
        (key === "base_url"
          ? form[key].trim().replace(/\/+$/, "")
          : form[key].trim()) === saved[key],
    );
  const hasSaved = (name: CredentialField) =>
    Boolean(
      sameService && !form.clear_credentials && saved?.saved_credentials[name],
    );

  useEffect(() => {
    dialog.current?.showModal();
    let active = true;
    getLLMSettings()
      .then((settings) => {
        if (!active) return;
        setSaved(settings);
        const {
          configured: _configured,
          saved_credentials: _credentials,
          ...publicSettings
        } = settings;
        setForm({ ...blankForm(settings.provider), ...publicSettings });
      })
      .catch((failure: unknown) => {
        if (active)
          setError(
            failure instanceof Error
              ? failure.message
              : "Could not load LLM settings.",
          );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  function update<K extends keyof LLMForm>(name: K, value: LLMForm[K]) {
    setForm((previous) => ({ ...previous, [name]: value }));
    setSuccess("");
    setError("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const mode =
      (event.nativeEvent as SubmitEvent).submitter?.getAttribute("value") ===
      "test"
        ? "test"
        : "save";
    setAction(mode);
    setError("");
    setSuccess("");
    try {
      if (mode === "test") {
        const result = await testLLMConnection(form);
        setSuccess(`${result.message} Save to apply these settings.`);
      } else {
        await saveLLMSettings(form);
        onSaved();
      }
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Could not update LLM settings.",
      );
    } finally {
      setAction(null);
    }
  }

  const secretInput = (
    name: CredentialField,
    label: string,
    required = false,
  ) => (
    <label className="settings-field" key={name}>
      <span>
        {label}
        {!required && " (optional)"}
      </span>
      <input
        type="password"
        autoComplete="new-password"
        value={form[name]}
        maxLength={32000}
        required={required && !hasSaved(name)}
        placeholder={
          hasSaved(name) ? "Saved — leave blank to keep" : "Enter credential"
        }
        onChange={(event) => update(name, event.target.value)}
      />
    </label>
  );
  const keyRequired = [
    "openai",
    "anthropic",
    "gemini",
    "azure",
    "openrouter",
  ].includes(form.provider);

  return (
    <dialog
      ref={dialog}
      className="llm-dialog"
      aria-labelledby="llm-title"
      aria-describedby="llm-description"
      onCancel={(event) => {
        if (action) event.preventDefault();
        else onClose();
      }}
    >
      <div className="settings-heading">
        <div>
          <p className="eyebrow">
            <Settings2 size={14} /> YOUR MODEL CONNECTION
          </p>
          <h2 id="llm-title">LLM settings</h2>
        </div>
        <button
          className="icon-button"
          aria-label="Close LLM settings"
          onClick={onClose}
          disabled={action !== null}
        >
          <X size={20} />
        </button>
      </div>
      <p id="llm-description">
        Choose a hosted service or a model running on your machine. You can
        change this connection at any time.
      </p>
      {loading && (
        <p role="status" className="settings-feedback">
          <LoaderCircle size={16} className="spin" /> Loading settings…
        </p>
      )}
      <form onSubmit={(event) => void submit(event)}>
        <fieldset disabled={pending || !saved}>
          <label className="settings-field">
            <span>Provider</span>
            <select
              value={form.provider}
              onChange={(event) => {
                setForm(blankForm(event.target.value as LLMProvider));
                setError("");
                setSuccess("");
              }}
            >
              {providers.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <p className="settings-hint">{preset.hint}</p>
          <label className="settings-field">
            <span>
              {form.provider === "azure" ? "Deployment name" : "Model ID"}
            </span>
            <input
              autoFocus
              required
              value={form.model}
              maxLength={256}
              autoComplete="off"
              placeholder="Exact model ID from your provider or local server"
              onChange={(event) => update("model", event.target.value)}
            />
          </label>
          <label className="settings-field">
            <span>
              Base URL
              {!["azure", "compatible"].includes(form.provider) &&
                " (optional)"}
            </span>
            <input
              type="url"
              required={["azure", "compatible"].includes(form.provider)}
              value={form.base_url}
              maxLength={2048}
              placeholder={preset.endpoint || "Default provider endpoint"}
              onChange={(event) => update("base_url", event.target.value)}
            />
          </label>
          {secretInput(
            "api_key",
            form.provider === "bedrock" ? "Bedrock API key" : "API key",
            keyRequired,
          )}
          {form.provider === "azure" && (
            <label className="settings-field">
              <span>Azure API version</span>
              <input
                required
                value={form.api_version}
                maxLength={100}
                placeholder="Version supported by your deployment"
                onChange={(event) => update("api_version", event.target.value)}
              />
            </label>
          )}
          {form.provider === "bedrock" && (
            <>
              <label className="settings-field">
                <span>AWS region</span>
                <input
                  value={form.aws_region_name}
                  maxLength={100}
                  placeholder="Region with access to this model"
                  onChange={(event) =>
                    update("aws_region_name", event.target.value)
                  }
                />
              </label>
              {secretInput("aws_access_key_id", "AWS access key ID")}
              {secretInput("aws_secret_access_key", "AWS secret access key")}
              {secretInput("aws_session_token", "AWS session token")}
            </>
          )}
          {form.provider === "vertex_ai" && (
            <>
              <label className="settings-field">
                <span>Google Cloud project</span>
                <input
                  value={form.vertex_project}
                  maxLength={256}
                  onChange={(event) =>
                    update("vertex_project", event.target.value)
                  }
                />
              </label>
              <label className="settings-field">
                <span>Vertex location</span>
                <input
                  value={form.vertex_location}
                  maxLength={100}
                  onChange={(event) =>
                    update("vertex_location", event.target.value)
                  }
                />
              </label>
              {secretInput("vertex_credentials", "Service account JSON")}
            </>
          )}
          <label className="settings-field">
            <span>Structured output</span>
            <select
              value={form.output_mode}
              onChange={(event) =>
                update("output_mode", event.target.value as "tools" | "json")
              }
            >
              <option value="tools">Tool calling</option>
              <option value="json">JSON mode</option>
            </select>
          </label>
          <p className="settings-hint">
            The model must support tool calling or JSON output. Test the
            connection to check compatibility. Endpoint addresses are reached
            from the backend.
          </p>
          {saved &&
            Object.values(saved.saved_credentials).some(Boolean) &&
            sameService && (
              <label className="settings-checkbox">
                <input
                  type="checkbox"
                  checked={form.clear_credentials}
                  onChange={(event) =>
                    update("clear_credentials", event.target.checked)
                  }
                />
                Forget existing credentials when saving (new values above
                replace them)
              </label>
            )}
          <p className="settings-privacy">
            Credentials are saved in a private file on this computer, outside
            source control. They are not stored in your browser. Explanations
            send the selected function and its immediate context to the service
            you choose.
          </p>
          <div className="settings-actions">
            <button className="button" type="submit" value="test">
              {action === "test" && <LoaderCircle size={15} className="spin" />}
              Test connection
            </button>
            <button className="button primary" type="submit" value="save">
              {action === "save" && <LoaderCircle size={15} className="spin" />}
              Save settings
            </button>
          </div>
        </fieldset>
        {error && (
          <p role="alert" className="settings-feedback settings-error">
            {error}
          </p>
        )}
        {success && (
          <p role="status" className="settings-feedback settings-success">
            {success}
          </p>
        )}
        <p className="settings-hint">
          Testing sends a small request and may use provider credits. Saving
          applies immediately; no restart is needed.
        </p>
      </form>
    </dialog>
  );
}
