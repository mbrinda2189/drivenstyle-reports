/*
 * month.tsx - The month being worked on, shared by the monthly screens
 * ====================================================================
 *
 * WHAT THIS FILE DOES
 * -------------------
 * Generate reports, Scan review and Monthly inputs all work on ONE month.
 * Choosing September on one of them must show September on the others,
 * also after the page is refreshed - so the choice is kept in the browser
 * (localStorage) under "dns-month".
 *
 * The first time, it is LAST month: the reports are prepared before the
 * 7th for the month just ended (the desktop tool's rule).
 *
 *   useMonth()      -> ["2026-09", setMonth]
 *   <MonthPicker/>  -> the Month and Year drop-downs
 *   <Chooser/>      -> a "type to find" box over a long list (products,
 *                      executives, cars); gives back the chosen id
 */
import { useEffect, useId, useState } from "react";
import { Choice } from "./api";

const KEY = "dns-month";
export const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
                            "August", "September", "October", "November", "December"];

function lastMonth(): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function useMonth(): [string, (month: string) => void] {
  const [month, setMonth] = useState(() => {
    const saved = window.localStorage.getItem(KEY) ?? "";
    return /^\d{4}-\d{2}$/.test(saved) ? saved : lastMonth();
  });
  useEffect(() => window.localStorage.setItem(KEY, month), [month]);
  return [month, setMonth];
}

/** "2026-09" -> "September 2026". */
export function monthLabel(month: string): string {
  const [year, mon] = month.split("-").map(Number);
  return `${MONTH_NAMES[mon - 1]} ${year}`;
}

export function MonthPicker({ month, onChange, disabled }:
    { month: string; onChange: (m: string) => void; disabled?: boolean }) {
  const [year, mon] = month.split("-").map(Number);
  const thisYear = new Date().getFullYear();
  const years = [...new Set([thisYear - 2, thisYear - 1, thisYear, thisYear + 1, year])].sort();
  const set = (y: number, m: number) => onChange(`${y}-${String(m).padStart(2, "0")}`);
  return (
    <div className="month-picker">
      <label>Month
        <select value={mon} disabled={disabled} onChange={(e) => set(year, Number(e.target.value))}>
          {MONTH_NAMES.map((name, i) => <option key={name} value={i + 1}>{name}</option>)}
        </select>
      </label>
      <label>Year
        <select value={year} disabled={disabled} onChange={(e) => set(Number(e.target.value), mon)}>
          {years.map((y) => <option key={y}>{y}</option>)}
        </select>
      </label>
    </div>
  );
}

/**
 * Type a few letters, pick from the matching names. The list can hold a
 * couple of hundred products without slowing the page, because the browser
 * itself does the searching. `onPick` gets the id, or null while the text
 * is not exactly one of the names.
 */
export function Chooser({ choices, placeholder, label, start, onPick }:
    { choices: Choice[]; placeholder: string; label: string; start?: number;
      onPick: (id: number | null) => void }) {
  const id = useId();
  const [text, setText] = useState(() => choices.find((c) => c.id === start)?.text ?? "");
  const change = (value: string) => {
    setText(value);
    onPick(choices.find((c) => c.text === value)?.id ?? null);
  };
  return (
    <>
      <input className="chooser" list={id} value={text} placeholder={placeholder} aria-label={label}
             onChange={(e) => change(e.target.value)} onClick={(e) => e.stopPropagation()} />
      <datalist id={id}>{choices.map((c) => <option key={c.id} value={c.text} />)}</datalist>
    </>
  );
}
