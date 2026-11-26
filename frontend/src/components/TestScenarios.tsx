import type { SimulatedTestCase, TestSuite } from "@/types/api";
import "./TestScenarios.css";

const categories: Record<SimulatedTestCase["category"], string> = {
  happy_path: "Happy path",
  transformation: "Data transformation",
  edge_case: "Edge case",
  boundary: "Boundary",
};

export default function TestScenarios({ suite }: { suite: TestSuite }) {
  if (!suite.scenarios?.length) return null;
  return (
    <section className="test-scenarios">
      <h3>Simulated cases</h3>
      <p className="prose">
        These are model predictions. Run the tests in Docker to check actual behavior.
      </p>
      {suite.purpose && <p className="prose">{suite.purpose}</p>}
      {suite.scenarios.map((scenario, index) => (
        <details key={index} open={index === 0}>
          <summary>
            <strong>{scenario.name}</strong>
            <small>{categories[scenario.category]}</small>
          </summary>
          <div className="scenario-body">
            <h4>Input</h4>
            <pre>
              <code>{scenario.input}</code>
            </pre>
            {scenario.steps.length > 0 && (
              <>
                <h4>Predicted steps</h4>
                <ol>
                  {scenario.steps.map((step, stepIndex) => (
                    <li key={stepIndex}>{step}</li>
                  ))}
                </ol>
              </>
            )}
            <div className="scenario-outputs">
              <div>
                <h4>Expected outcome</h4>
                <pre>
                  <code>{scenario.expected_output}</code>
                </pre>
              </div>
              <div>
                <h4>Model prediction</h4>
                <pre>
                  <code>{scenario.predicted_output}</code>
                </pre>
              </div>
            </div>
            {scenario.rationale && (
              <p className="prose">{scenario.rationale}</p>
            )}
          </div>
        </details>
      ))}
    </section>
  );
}
