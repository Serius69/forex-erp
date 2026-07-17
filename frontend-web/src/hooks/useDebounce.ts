// src/hooks/useDebounce.ts
import { useEffect, useState } from 'react';

/**
 * Devuelve una versión "debounced" de `value` que solo se actualiza tras
 * `delay` ms sin cambios. Útil para no disparar un fetch por cada tecla en
 * un buscador: el input sigue actualizándose al instante, pero el valor que
 * alimenta la request se estabiliza tras la pausa.
 */
export function useDebounce<T>(value: T, delay = 350): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);

  return debounced;
}
