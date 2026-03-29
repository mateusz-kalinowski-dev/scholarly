import { useReducer, useEffect, useCallback } from 'react';

interface State<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

type Action<T> =
  | { type: 'FETCH_START' }
  | { type: 'FETCH_SUCCESS'; payload: T }
  | { type: 'FETCH_ERROR'; error: string };

function reducer<T>(state: State<T>, action: Action<T>): State<T> {
  switch (action.type) {
    case 'FETCH_START':
      return { ...state, loading: true, error: null };
    case 'FETCH_SUCCESS':
      return { data: action.payload, loading: false, error: null };
    case 'FETCH_ERROR':
      return { ...state, loading: false, error: action.error };
  }
}

interface UseApiState<T> extends State<T> {
  refetch: () => void;
}

export function useApi<T>(fetcher: () => Promise<T>): UseApiState<T> {
  const [state, dispatch] = useReducer(reducer<T>, {
    data: null,
    loading: true,
    error: null,
  });
  const [tick, setTick] = useReducer((n: number) => n + 1, 0);

  const refetch = useCallback(() => setTick(), []);

  useEffect(() => {
    let cancelled = false;
    dispatch({ type: 'FETCH_START' });
    fetcher()
      .then((result) => {
        if (!cancelled) dispatch({ type: 'FETCH_SUCCESS', payload: result });
      })
      .catch((err: unknown) => {
        if (!cancelled)
          dispatch({
            type: 'FETCH_ERROR',
            error: err instanceof Error ? err.message : String(err),
          });
      });
    return () => {
      cancelled = true;
    };
  }, [fetcher, tick]);

  return { ...state, refetch };
}
