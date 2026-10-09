/*
 * ComingSoon.tsx - A screen that is planned but not built yet
 * ===========================================================
 * Shows the screen's name, what it will do, and the step of the plan
 * (web/README.md) that builds it - so the whole layout can be clicked
 * through from v0.23.0, and nobody mistakes an empty screen for a fault.
 * Each real screen replaces its ComingSoon line in App.tsx.
 */
interface Props {
  title: string;
  about: string;
  step: number;
}

export default function ComingSoon({ title, about, step }: Props) {
  return (
    <>
      <h1>{title}</h1>
      <div className="card soon">
        <div className="soon-step">Comes in step {step}</div>
        <p>{about}</p>
      </div>
    </>
  );
}
