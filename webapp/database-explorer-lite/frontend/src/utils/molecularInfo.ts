export interface MolInfo {
  atomCount: number
  formula: string
  weight: number
}

const ATOMIC_MASS: Record<string, number> = {
  H: 1.008, He: 4.003, Li: 6.941, Be: 9.012, B: 10.811,
  C: 12.011, N: 14.007, O: 15.999, F: 18.998, Ne: 20.180,
  Na: 22.990, Mg: 24.305, Al: 26.982, Si: 28.086, P: 30.974,
  S: 32.065, Cl: 35.453, Ar: 39.948, K: 39.098, Ca: 40.078,
  As: 74.922, Se: 78.971, Br: 79.904, I: 126.904, Hg: 200.590, Bi: 208.980,
}

function buildHillFormula(counts: Record<string, number>): string {
  const keys = Object.keys(counts).sort((a, b) => {
    if (a === 'C') return -1
    if (b === 'C') return 1
    if (a === 'H') return -1
    if (b === 'H') return 1
    return a.localeCompare(b)
  })
  return keys.map(el => (counts[el] === 1 ? el : `${el}${counts[el]}`)).join('')
}

export function parseMolInfo(xyz: string): MolInfo | null {
  const lines = xyz.trim().split(/\r?\n/)
  const atomCount = parseInt(lines[0], 10)
  if (!Number.isFinite(atomCount) || atomCount <= 0 || lines.length < atomCount + 2) return null
  const counts: Record<string, number> = {}
  for (const line of lines.slice(2, atomCount + 2)) {
    const sym = line.trim().split(/\s+/)[0]
    if (sym) counts[sym] = (counts[sym] ?? 0) + 1
  }
  if (Object.keys(counts).length === 0) return null
  const formula = buildHillFormula(counts)
  const weight = Object.entries(counts).reduce(
    (s, [el, n]) => s + (ATOMIC_MASS[el] ?? 0) * n,
    0,
  )
  return { atomCount, formula, weight }
}
