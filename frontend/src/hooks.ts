import { useEffect, useState } from 'react';
import type { LoadState } from './types';

export const useAsyncResource = <T,>(
  loader: (signal: AbortSignal) => Promise<T>,
): LoadState<T> => {
  const [state, setState] = useState<LoadState<T>>({
    status: 'loading',
    data: null,
    message: null,
  });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading', data: null, message: null });

    loader(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setState({ status: 'ready', data, message: null });
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          status: 'error',
          data: null,
          message: error instanceof Error ? error.message : 'The request failed.',
        });
      });

    return () => controller.abort();
  }, [loader]);

  return state;
};
