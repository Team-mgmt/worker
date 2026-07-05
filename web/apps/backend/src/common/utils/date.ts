/**
 * Returns a new Date representing `months` calendar months before `from`.
 *
 * Plain `Date#setMonth(month - n)` overflows on month-end days (e.g.
 * `2026-08-31` minus 6 months becomes `2026-03-03` because "February 31"
 * rolls into March). This helper clamps the day to the last valid day of
 * the target month so the resulting date stays inside the intended month.
 */
export function subtractMonthsClamped(from: Date, months: number): Date {
  const result = new Date(from);
  const originalDay = from.getDate();

  // Snap to day 1 before shifting the month to avoid the overflow described
  // above. Then restore the original day, clamped to the last day of the
  // resulting month.
  result.setDate(1);
  result.setMonth(result.getMonth() - months);

  const lastDayOfTargetMonth = new Date(
    result.getFullYear(),
    result.getMonth() + 1,
    0,
  ).getDate();
  result.setDate(Math.min(originalDay, lastDayOfTargetMonth));
  return result;
}
